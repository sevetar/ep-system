<script setup>
import { computed, ref, onMounted } from 'vue'
import { ElMessage, ElLoading } from 'element-plus'
import { UserFilled } from '@element-plus/icons-vue'
import useUserInfoStore from '@/stores/userInfo.js'
import { userInfoService, userInfoUpdateService } from '@/api/user.js'
import { useRouter } from 'vue-router'

const userInfoStore = useUserInfoStore()
const canApplyToBeRepairman = computed(() => {
  const roles = Array.isArray(userInfoStore.role) ? userInfoStore.role : []
  return !roles.includes(1) && !roles.includes(3)
})
const userInfo = ref({
  username: '',
  password: '',
  phone: '',
  avatar: '',
  status: 1
})

const rules = {
  username: [
    { required: true, message: '请输入登录名称', trigger: 'blur' },
    {
      pattern: /^\S{2,20}$/,
      message: '登录名称应为2-20位非空字符',
      trigger: 'blur'
    }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    {
      min: 6,
      message: '密码至少为6位',
      trigger: 'blur'
    }
  ],
  phone: [
    { required: true, message: '请输入手机号码', trigger: 'blur' },
    {
      pattern: /^1[3-9]\d{9}$/,
      message: '请输入正确的手机号码',
      trigger: 'blur'
    }
  ]
}

// 获取用户信息
const loadUserInfo = async () => {
  const loading = ElLoading.service({ lock: true })
  try {
    const res = await userInfoService()
    const user = res.data?.data?.user
    if (user) {
      userInfo.value = {
        username: user.username || '',
        password: user.password || '',
        phone: user.phone || '',
        avatar: user.avatar || '',
        status: user.status ?? 1
      }
      userInfoStore.setInfo(user)
    }
  } catch (error) {
    ElMessage.error('获取用户信息失败')
  } finally {
    loading.close()
  }
}

// 提交修改
const handleSubmit = async () => {
  const loading = ElLoading.service({ lock: true })
  try {
    const res = await userInfoUpdateService({ ...userInfo.value })
    ElMessage.success(res.data?.msg || '修改成功')
    await loadUserInfo()
  } catch (error) {
    ElMessage.error(error.response?.data?.msg || '修改失败')
  } finally {
    loading.close()
  }
}

const router = useRouter()
const applyToBeRepairman = () => {
  if (!canApplyToBeRepairman.value) {
    ElMessage.info('当前账号已有对应权限，无需重复申请')
    return
  }
  router.push('/user/applytoberepairman')
}

onMounted(() => {
  loadUserInfo()
})
</script>

<template>
  <el-card class="page-container">
    <template #header>
      <div class="header">
        <span>用户基本信息</span>
      </div>
    </template>

    <el-row>
      <el-col :span="12">
        <el-form :model="userInfo" :rules="rules" label-width="100px" size="large">
          <el-form-item label="登录名称" prop="username">
            <el-input v-model="userInfo.username" />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input v-model="userInfo.password" type="password" show-password />
          </el-form-item>

          <el-form-item label="手机号码" prop="phone">
            <el-input v-model="userInfo.phone" />
          </el-form-item>

          <el-form-item label="账号状态">
            <el-tag :type="userInfo.status === 1 ? 'success' : 'danger'">
              {{ userInfo.status === 1 ? '正常' : '禁用' }}
            </el-tag>
          </el-form-item>

          <el-form-item>
            <el-button type="primary" @click="handleSubmit">保存修改</el-button>
            <el-button v-if="canApplyToBeRepairman" type="success" @click="applyToBeRepairman">
              申请成为维修人员
            </el-button>
            <el-tag v-else type="success">已拥有维修或管理权限</el-tag>
          </el-form-item>
        </el-form>
      </el-col>

      <el-col :span="12" class="avatar-col">
        <div class="avatar-uploader">
          <img v-if="userInfo.avatar" :src="userInfo.avatar" class="avatar" alt="用户头像" />
          <el-icon v-else class="avatar-icon">
            <UserFilled />
          </el-icon>
          <div class="avatar-actions">
            <el-button type="primary" size="small">更换头像</el-button>
          </div>
        </div>
      </el-col>
    </el-row>
  </el-card>
</template>

<style scoped>
.page-container {
  min-height: 100%;
  padding: 20px;
}

.header {
  font-size: 20px;
  font-weight: bold;
  border-bottom: 1px solid var(--el-border-color);
  padding-bottom: 10px;
}

.avatar-col {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 20px;
}

.avatar-uploader {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 15px;
  padding: 20px;
  border-radius: 8px;
  background-color: var(--el-fill-color-light);
}

.avatar {
  width: 150px;
  height: 150px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px dashed var(--el-border-color);
}

.avatar-icon {
  font-size: 150px;
  color: var(--el-text-color-secondary);
  padding: 10px;
  border-radius: 50%;
  background-color: var(--el-fill-color);
}

.avatar-actions {
  display: flex;
  gap: 10px;
}
</style>
