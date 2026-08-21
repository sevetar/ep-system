import { createRouter, createWebHashHistory } from 'vue-router'

import Login from '@/views/Login.vue'
import Layout from '@/views/Layout.vue'
import { useTokenStore } from '@/stores/token.js'

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'login', component: Login, meta: { title: '登录' } },
  {
    path: '/layout',
    component: Layout,
    redirect: '/dashboard',
    meta: { requiresAuth: true },
    children: [
      {
        path: '/dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '运行总览' }
      },
      {
        path: '/agent/console',
        component: () => import('@/views/agent/AgentConsole.vue'),
        meta: { title: 'AI 智能中心' }
      },
      {
        path: '/device/category',
        component: () => import('@/views/device/deviceCategory.vue'),
        meta: { title: '设备分类' }
      },
      {
        path: '/device/manage',
        component: () => import('@/views/device/deviceManage.vue'),
        meta: { title: '设备管理' }
      },
      {
        path: '/device/instance/:id?',
        component: () => import('@/views/device/deviceInstance.vue'),
        props: true,
        meta: { title: '设备实例' }
      },
      {
        path: '/device/DetailInfo/:id',
        component: () => import('@/views/device/deviceDetailInfo.vue'),
        props: true,
        meta: { title: '设备详情' }
      },
      {
        path: '/order/orderManage',
        component: () => import('@/views/order/OrderManage.vue'),
        meta: { title: '工单中心' }
      },
      {
        path: '/user/info',
        component: () => import('@/views/user/UserInfo.vue'),
        meta: { title: '个人资料' }
      },
      {
        path: '/user/order',
        component: () => import('@/views/user/UserOrder.vue'),
        meta: { title: '我的工单' }
      },
      {
        path: '/user/applytoberepairman',
        component: () => import('@/views/user/ApplytoRepairman.vue'),
        meta: { title: '维修员申请' }
      },
      {
        path: '/user/userdevice',
        component: () => import('@/views/user/Userdevice.vue'),
        meta: { title: '我的设备' }
      },
      {
        path: '/message/manage',
        component: () => import('@/views/message/message.vue'),
        meta: { title: '消息协作' }
      },
      {
        path: '/admin/controller',
        component: () => import('@/views/admin/controller.vue'),
        meta: { title: '管理控制台' }
      },
      {
        path: '/admin/deviceApproval',
        component: () => import('@/views/admin/deviceApproval.vue'),
        meta: { title: '维修审批' }
      },
      {
        path: '/admin/orderHistory',
        component: () => import('@/views/admin/OrderHistory.vue'),
        meta: { title: '工单历史' }
      },
      {
        path: '/admin/deviceApprovalDetail/:id',
        component: () => import('@/views/admin/deviceApprovalDetail.vue'),
        props: true,
        meta: { title: '审批详情' }
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.beforeEach((to) => {
  document.title = `${to.meta.title || '工作台'} · FlowFix`
  const tokenStore = useTokenStore()
  if (to.meta.requiresAuth && !tokenStore.token) return '/login'
  return true
})

export default router
