<script setup>
import { Connection, Lock, Phone, User } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { userLoginService, userRegisterService, userRoleService } from '@/api/user.js'
import useUserInfoStore from '@/stores/userInfo.js'
import { useTokenStore } from '@/stores/token.js'

const isRegister = ref(false)
const loading = ref(false)
const formRef = ref()
const router = useRouter()
const tokenStore = useTokenStore()
const userInfoStore = useUserInfoStore()
const formTitle = computed(() => isRegister.value ? '创建平台账号' : '欢迎回到 FlowFix')

const formData = ref({ username: '', password: '', rePassword: '', phonenum: '' })

const validateRepeatedPassword = (_rule, value, callback) => {
  if (!value) callback(new Error('请再次输入密码'))
  else if (value !== formData.value.password) callback(new Error('两次密码输入不一致'))
  else callback()
}

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 16, message: '用户名长度为 3–16 位', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 5, max: 16, message: '密码长度为 5–16 位', trigger: 'blur' }
  ],
  rePassword: [{ validator: validateRepeatedPassword, trigger: 'blur' }],
  phonenum: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: /^1\d{10}$/, message: '请输入 11 位手机号', trigger: 'blur' }
  ]
}

const switchMode = register => {
  isRegister.value = register
  formData.value = { username: '', password: '', rePassword: '', phonenum: '' }
  formRef.value?.clearValidate()
}

const submit = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    if (isRegister.value) {
      await userRegisterService(formData.value)
      ElMessage.success('账号创建成功，请登录')
      switchMode(false)
      return
    }

    const result = await userLoginService(formData.value)
    const payload = result.data.data
    tokenStore.setToken(payload.token)
    userInfoStore.setInfo(payload.user || {})
    try {
      const roleResult = await userRoleService()
      userInfoStore.setRole(roleResult.data.data?.roleIds || [])
    } catch {
      userInfoStore.setRole([])
      ElMessage.warning('角色信息暂未加载，部分菜单可能不可见')
    }
    ElMessage.success('登录成功')
    await router.replace('/dashboard')
  } catch {
    // 请求层已经展示具体错误；这里结束事件 Promise，避免 Vue 报未处理异常。
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-cover">
      <div class="cover-grid"></div>
      <div class="cover-orb orb-one"></div>
      <div class="cover-orb orb-two"></div>

      <div class="cover-brand">
        <span class="brand-mark"><Connection /></span>
        <div><strong>FlowFix</strong><small>INTELLIGENT OPERATIONS</small></div>
      </div>

      <div class="cover-copy">
        <span class="cover-kicker">设备运维的新工作方式</span>
        <h1>让每一次设备响应，<br><em>更快、更稳、更聪明。</em></h1>
        <p>统一设备资产、维修工单、协作消息与 AI 派单决策，让真实业务状态始终留在 Java，让智能决策清晰可追溯。</p>
        <div class="cover-metrics">
          <div><strong>01</strong><span>统一运维入口</span></div>
          <div><strong>02</strong><span>确定性智能派单</span></div>
          <div><strong>03</strong><span>全链路审计追踪</span></div>
        </div>
      </div>

      <div class="cover-system-card">
        <div class="system-pulse"><span></span></div>
        <div><strong>Integration stack ready</strong><small>Java · Agent · MySQL · Redis · RabbitMQ</small></div>
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-form-wrap">
        <div class="mobile-brand"><span class="brand-mark"><Connection /></span><strong>FlowFix</strong></div>
        <span class="form-kicker">{{ isRegister ? 'JOIN FLOWFIX' : 'WELCOME BACK' }}</span>
        <h2>{{ formTitle }}</h2>
        <p class="form-description">
          {{ isRegister ? '填写基本信息，开始管理你的设备。' : '登录设备运维工作台，继续处理今天的任务。' }}
        </p>

        <el-form
          ref="formRef"
          :model="formData"
          :rules="rules"
          size="large"
          label-position="top"
          @keyup.enter="submit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input v-model="formData.username" :prefix-icon="User" placeholder="请输入用户名" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input v-model="formData.password" :prefix-icon="Lock" type="password" show-password placeholder="请输入密码" autocomplete="current-password" />
          </el-form-item>
          <template v-if="isRegister">
            <el-form-item label="确认密码" prop="rePassword">
              <el-input v-model="formData.rePassword" :prefix-icon="Lock" type="password" show-password placeholder="再次输入密码" />
            </el-form-item>
            <el-form-item label="手机号" prop="phonenum">
              <el-input v-model="formData.phonenum" :prefix-icon="Phone" placeholder="请输入 11 位手机号" />
            </el-form-item>
          </template>
          <div v-else class="auth-options">
            <el-checkbox>记住登录状态</el-checkbox>
            <span>安全登录由平台统一保护</span>
          </div>
          <el-button class="auth-submit" type="primary" :loading="loading" @click="submit">
            {{ isRegister ? '创建账号' : '进入工作台' }}
          </el-button>
        </el-form>

        <p class="auth-switch">
          {{ isRegister ? '已经拥有账号？' : '首次使用 FlowFix？' }}
          <button type="button" @click="switchMode(!isRegister)">
            {{ isRegister ? '返回登录' : '创建账号' }}
          </button>
        </p>
      </div>
      <div class="auth-legal">© 2026 FlowFix · 智能设备运维平台</div>
    </section>
  </main>
</template>
