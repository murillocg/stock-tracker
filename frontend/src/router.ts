import { createRouter, createWebHistory } from 'vue-router'
import PortfolioView from '@/views/PortfolioView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'portfolio', component: PortfolioView },
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
