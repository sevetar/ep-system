<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { submitRepairmanApplication, userRoleService } from '@/api/user.js'
import useUserInfoStore from '@/stores/userInfo.js'

const router = useRouter()
const userInfoStore = useUserInfoStore()
const form = ref()
const submitting = ref(false)
const checkingRole = ref(true)
const hasRepairmanRole = computed(() => {
  const roles = Array.isArray(userInfoStore.role) ? userInfoStore.role : []
  return roles.includes(3)
})

// 申请表单数据
const applicationForm = ref({
  applyReason: '',
  qualificationProof: ''
})

// 提交申请
const waitForRepairmanRole = async () => {
  for (let attempt = 0; attempt < 10; attempt++) {
    const result = await userRoleService()
    const roles = result.data.data?.roleIds || []
    userInfoStore.setRole(roles)
    if (roles.includes(3)) return true
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  return false
}

const submitApplication = async () => {
  const roleResult = await userRoleService()
  const roles = roleResult.data.data?.roleIds || []
  userInfoStore.setRole(roles)
  if (roles.includes(3)) {
    ElMessage.info('当前账号已拥有维修人员权限，无需重复申请')
    return
  }

  const valid = await form.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const result = await submitRepairmanApplication(applicationForm.value)
    if (result.data.code === 200) {
      ElMessage.success('申请已提交，正在等待审批结果')
      const approved = await waitForRepairmanRole()
      if (approved) {
        ElMessage.success('审核通过，已获得维修员权限')
        await router.replace('/dashboard')
      } else {
        ElMessage.info('申请仍在处理中，请稍后刷新页面')
      }
    } else {
      ElMessage.error(result.data.message || '申请提交失败')
    }
  } catch (error) {
    ElMessage.error('提交申请时出错')
    console.error(error)
  } finally {
    submitting.value = false
  }
}

// 表单验证规则
const rules = {
  applyReason: [
    { required: true, message: '请输入申请理由', trigger: 'blur' },
    { min: 10, max: 500, message: '申请理由需10-500个字符', trigger: 'blur' }
  ],
}



// 取消申请
const cancelApplication = () => {
  router.go(-1) // 返回上一页
}

onMounted(async () => {
  try {
    const result = await userRoleService()
    userInfoStore.setRole(result.data.data?.roleIds || [])
  } finally {
    checkingRole.value = false
  }
})
</script>

<template>
  <el-row class="application-page">
    <el-col :span="24" class="form-container">
      <el-skeleton v-if="checkingRole" :rows="5" animated />

      <el-result
        v-else-if="hasRepairmanRole"
        icon="success"
        title="已获得维修人员权限"
        sub-title="当前账号无需重复提交申请"
      >
        <template #extra>
          <el-button type="primary" @click="router.replace('/dashboard')">返回工作台</el-button>
        </template>
      </el-result>

      <el-form
        v-else
        ref="form"
        size="large" 
        :model="applicationForm" 
        :rules="rules"
        label-position="top"
        class="application-form"
      >
        <el-form-item>
          <h1>维修人员申请</h1>
        </el-form-item>

        <el-form-item label="申请理由" prop="applyReason">
          <el-input
            type="textarea"
            :rows="5"
            placeholder="请详细说明您申请成为维修人员的理由和相关经验"
            v-model="applicationForm.applyReason"
            resize="none"
          ></el-input>
        </el-form-item>

        <el-form-item label="资质说明（本地演示可选）" prop="qualificationProof">
          <el-input
            v-model="applicationForm.qualificationProof"
            placeholder="当前演示版未接入文件存储，可填写证书编号或说明"
          />
        </el-form-item>

        <el-form-item class="button-group">
          <el-button 
            type="primary" 
            class="button" 
            :loading="submitting"
            @click="submitApplication"
          >
            提交申请
          </el-button>
          <el-button 
            class="button" 
            :disabled="submitting"
            @click="cancelApplication"
          >
            取消
          </el-button>
        </el-form-item>
      </el-form>
    </el-col>
  </el-row>
</template>

<style lang="scss" scoped>
.application-page {
  min-height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  background-color: #f5f5f5;

  .form-container {
    width: 100%;
    max-width: 600px;
    padding: 40px;
    background-color: #fff;
    border-radius: 8px;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
  }

  h1 {
    margin-bottom: 30px;
    text-align: center;
    color: var(--el-color-primary);
  }

  .button-group {
    display: flex;
    justify-content: space-between;
  }

  .button {
    width: 48%;
  }

  .el-textarea :deep(.el-textarea__inner) {
    min-height: 120px !important;
  }

  .upload-demo {
    width: 100%;
  }

  .el-upload__tip {
    margin-top: 8px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}
</style>
