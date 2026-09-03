import { createRouter, createWebHistory } from 'vue-router'
import PortfolioView from '@/views/PortfolioView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'portfolio', component: PortfolioView },
    {
      // Its own route, not a tab. The watchlist answers a different question and
      // has a different shape — and as a tab, switching to it blanked the
      // portfolio while it refetched. A route also restores the back button.
      path: '/watchlist',
      name: 'watchlist',
      component: () => import('@/views/WatchlistView.vue'),
    },
    {
      path: '/stocks/:ticker',
      name: 'stock',
      // `props: true` passes the route param straight into the component as a
      // typed prop, so the view never reads from the router itself.
      component: () => import('@/views/StockDetailView.vue'),
      props: true,
    },
  ],
})
