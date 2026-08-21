<script setup>
import {
  Bell,
  CaretBottom,
  ChatDotRound,
  Connection,
  Cpu,
  DataAnalysis,
  Expand,
  Fold,
  MagicStick,
  Monitor,
  Setting,
  SwitchButton,
  Tickets,
  User,
  UserFilled
} from '@element-plus/icons-vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import avatar from '@/assets/default.png'
import { userRoleService } from '@/api/user.js'
import { connect, disconnect } from '@/utils/websocket.js'
import useUserInfoStore from '@/stores/userInfo.js'
import { useTokenStore } from '@/stores/token.js'

const route = useRoute()
const router = useRouter()
const tokenStore = useTokenStore()
const userInfoStore = useUserInfoStore()
const collapsed = ref(false)

const roles = computed(() => Array.isArray(userInfoStore.role) ? userInfoStore.role : [])
const hasRole = target => roles.value.includes(target)
const hasAnyRole = targets => targets.some(role => roles.value.includes(role))
const pageTitle = computed(() => route.meta.title || '运行总览')
const displayName = computed(() => (
  userInfoStore.info.nickname || userInfoStore.info.username || 'FlowFix 用户'
))
const roleLabel = computed(() => {
  if (hasRole(1)) return '平台管理员'
  if (hasRole(3)) return '维修工程师'
  return '设备用户'
})

const refreshRoles = async () => {
  try {
    const result = await userRoleService()
    userInfoStore.setRole(result.data.data?.roleIds || [])
  } catch {
    // 请求层已经展示错误，保留当前角色以避免页面闪烁。
  }
}

onMounted(async () => {
  await refreshRoles()
  connect()
})
onUnmounted(() => {
  void disconnect().catch(error => console.warn('WebSocket 断开失败', error))
})

const logout = () => {
  // 退出必须先同步清空本地认证状态，不能被 WebSocket 或路由异常阻断。
  tokenStore.removeToken()
  userInfoStore.removeInfo()
  userInfoStore.removeRole()
  localStorage.removeItem('token')
  localStorage.removeItem('userInfo')

  void disconnect().catch(error => console.warn('WebSocket 断开失败', error))
  window.location.replace(`${window.location.pathname}${window.location.search}#/login`)
}

const handleCommand = async command => {
  if (command === 'logout') return
  await router.push(`/user/${command}`)
}
</script>

<template>
  <div class="app-shell" :class="{ 'is-collapsed': collapsed }">
    <aside class="app-sidebar">
      <button class="brand" type="button" @click="router.push('/dashboard')">
        <span class="brand-mark"><Connection /></span>
        <span v-show="!collapsed" class="brand-copy">
          <strong>FlowFix</strong>
          <small>智能设备运维平台</small>
        </span>
      </button>

      <div v-show="!collapsed" class="nav-caption">工作空间</div>
      <el-menu
        :default-active="route.path"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="sidebar-menu"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon><template #title>运行总览</template>
        </el-menu-item>
        <el-menu-item index="/agent/console">
          <el-icon><MagicStick /></el-icon><template #title>AI 智能中心</template>
        </el-menu-item>
        <el-sub-menu index="devices">
          <template #title><el-icon><Cpu /></el-icon><span>设备资产</span></template>
          <el-menu-item v-if="hasRole(1)" index="/device/category">设备分类</el-menu-item>
          <el-menu-item index="/device/manage">设备模型</el-menu-item>
          <el-menu-item index="/device/instance">设备实例</el-menu-item>
        </el-sub-menu>
        <el-menu-item v-if="hasAnyRole([1, 3])" index="/order/orderManage">
          <el-icon><Tickets /></el-icon><template #title>工单中心</template>
        </el-menu-item>
        <el-sub-menu v-if="hasRole(1)" index="admin">
          <template #title><el-icon><Setting /></el-icon><span>平台管理</span></template>
          <el-menu-item index="/admin/deviceApproval">维修审批</el-menu-item>
          <el-menu-item index="/admin/orderHistory">工单历史</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="personal">
          <template #title><el-icon><UserFilled /></el-icon><span>个人中心</span></template>
          <el-menu-item index="/user/info">基本资料</el-menu-item>
          <el-menu-item index="/user/order">我的工单</el-menu-item>
          <el-menu-item index="/user/userdevice">我的设备</el-menu-item>
          <el-menu-item v-if="!hasAnyRole([1, 3])" index="/user/applytoberepairman">
            申请维修员
          </el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/message/manage">
          <el-icon><ChatDotRound /></el-icon><template #title>消息协作</template>
        </el-menu-item>
      </el-menu>

      <div v-show="!collapsed" class="sidebar-status">
        <span class="status-dot"></span>
        <div><strong>联调环境在线</strong><small>Java · Agent · Docker</small></div>
      </div>
    </aside>

    <section class="app-stage">
      <header class="topbar">
        <div class="topbar-left">
          <button class="icon-button" type="button" @click="collapsed = !collapsed">
            <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon>
          </button>
          <div>
            <div class="eyebrow">FLOWFIX OPERATIONS</div>
            <h1>{{ pageTitle }}</h1>
          </div>
        </div>
        <div class="topbar-actions">
          <button class="icon-button notification-button" type="button" @click="router.push('/message/manage')">
            <el-icon><Bell /></el-icon><span></span>
          </button>
          <el-dropdown placement="bottom-end" @command="handleCommand">
            <button class="profile-button" type="button">
              <el-avatar :size="38" :src="userInfoStore.info.userPic || avatar" />
              <span class="profile-copy"><strong>{{ displayName }}</strong><small>{{ roleLabel }}</small></span>
              <el-icon><CaretBottom /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="info" :icon="User">个人资料</el-dropdown-item>
                <el-dropdown-item divided :icon="SwitchButton" @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="app-content">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>

      <footer class="app-footer">
        <span>FlowFix 智能设备运维平台</span>
        <span>Java Services · AI Agent · 2026</span>
      </footer>
    </section>
  </div>
</template>
