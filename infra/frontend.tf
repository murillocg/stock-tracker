# Static hosting for the Vue app: a private S3 bucket fronted by CloudFront.
#
# No custom domain. CloudFront issues a *.cloudfront.net hostname with a managed
# TLS certificate at no cost, which is enough for a single-user app — a domain can
# be added later without changing anything else here.

locals {
  dist_dir = "${path.module}/../frontend/dist"

  # S3 serves whatever Content-Type it is told, and a .js file served as
  # binary/octet-stream is refused by the browser as a module. Terraform does not
  # infer these, so the mapping has to be explicit.
  content_types = {
    html  = "text/html; charset=utf-8"
    js    = "text/javascript; charset=utf-8"
    css   = "text/css; charset=utf-8"
    json  = "application/json"
    map   = "application/json"
    svg   = "image/svg+xml"
    ico   = "image/x-icon"
    png   = "image/png"
    woff2 = "font/woff2"
    txt   = "text/plain; charset=utf-8"
  }
}

# Bucket names are globally unique across every AWS account, so the account id
# keeps this from colliding with someone else's "stock-tracker-frontend".
resource "aws_s3_bucket" "frontend" {
  bucket = "${var.project_name}-frontend-${data.aws_caller_identity.current.account_id}"
}

# The bucket is never public. CloudFront reaches it through Origin Access Control,
# which means the only way to the files is through the distribution — so the
# cache, the TLS and the throttling cannot be bypassed by hitting S3 directly.
resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.project_name}-frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "frontend_bucket" {
  statement {
    sid       = "AllowCloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    # Scoped to this one distribution, not to CloudFront in general.
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket.json
}

# Upload every built file. `fileset` is evaluated at plan time, so `npm run build`
# has to run first — which is why the Makefile makes it a prerequisite.
resource "aws_s3_object" "frontend" {
  for_each = fileset(local.dist_dir, "**")

  bucket = aws_s3_bucket.frontend.id
  key    = each.value
  source = "${local.dist_dir}/${each.value}"

  content_type = lookup(
    local.content_types,
    lower(reverse(split(".", each.value))[0]),
    "application/octet-stream"
  )

  # Vite fingerprints asset filenames (index-C9PB.js), so those are safe to cache
  # forever — a new build produces a new name. index.html must NOT be cached, or
  # browsers keep loading the old bundle after a deploy.
  cache_control = endswith(each.value, ".html") ? "no-cache" : "public, max-age=31536000, immutable"

  # Without this Terraform cannot tell that a rebuilt file changed, and would skip
  # re-uploading it.
  etag = filemd5("${local.dist_dir}/${each.value}")
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "${var.project_name} frontend"
  price_class         = var.cloudfront_price_class

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # AWS-managed "CachingOptimized" policy. Using the managed id avoids
    # hand-rolling a cache policy resource that would only restate the defaults.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  # Vue Router uses real paths (/stocks/PETR4), but S3 has no object at that key
  # and answers 403. Rewriting both 403 and 404 to index.html with a 200 is what
  # lets the SPA router handle the route — otherwise a page refresh or a shared
  # link 404s.
  dynamic "custom_error_response" {
    for_each = [403, 404]

    content {
      error_code            = custom_error_response.value
      response_code         = 200
      response_page_path    = "/index.html"
      error_caching_min_ttl = 0
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # The default *.cloudfront.net certificate. A custom domain would need an ACM
  # certificate in us-east-1 plus an aliases block; nothing else would change.
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
