import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/login' },
  { path: '/login', component: () => import('@/views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/views/Layout.vue'),
    children: [
      { path: 'factory/production', component: () => import('@/views/factory/Production.vue') },
      { path: 'factory/outbound', component: () => import('@/views/factory/Outbound.vue') },
      { path: 'transport/telemetry', component: () => import('@/views/transport/Telemetry.vue') },
      { path: 'transport/alerts', component: () => import('@/views/transport/Alerts.vue') },
      { path: 'site/entry', component: () => import('@/views/site/Entry.vue') },
      { path: 'site/hoisting', component: () => import('@/views/site/Hoisting.vue') },
      { path: 'site/joint', component: () => import('@/views/site/Joint.vue') },
      { path: 'site/protection', component: () => import('@/views/site/Protection.vue') },
      { path: 'supervisor/concealed', component: () => import('@/views/supervisor/Concealed.vue') },
      { path: 'owner/dashboard', component: () => import('@/views/owner/Dashboard.vue') },
      { path: 'owner/archives', component: () => import('@/views/owner/Archives.vue') },
      { path: 'owner/progress', component: () => import('@/views/owner/Progress.vue') },
      { path: 'quality/inspections', component: () => import('@/views/quality/Inspections.vue') },
      { path: 'quality/workbench', component: () => import('@/views/quality/Workbench.vue') },
      { path: 'quality/mobile', component: () => import('@/views/quality/MobileInspection.vue') },
      { path: 'contractor/rectification', component: () => import('@/views/contractor/Rectification.vue') },
      { path: 'operator/maintenance', component: () => import('@/views/operator/Maintenance.vue') },
      { path: 'trace', component: () => import('@/views/Trace.vue') },
      { path: 'trace/:code', component: () => import('@/views/Trace.vue') },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.isAuthed) {
    return { path: '/login' }
  }
  return true
})

export default router
