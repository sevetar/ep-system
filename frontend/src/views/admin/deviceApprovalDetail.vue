<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMaintainRecordById, approvalMaintainRecord } from '@/api/device.js'
import useUserInfoStore from '@/stores/userInfo.js'

const route = useRoute()
const router = useRouter()
const userStore = useUserInfoStore()
const id = route.params.id

const record = ref(null)
const loading = ref(false)
const editDrawerVisible = ref(false)
const editForm = ref({
  id: '',
  status: '',
  operatorId: '',
  approvalId: userStore.info.id || '', // 自动绑定当前用户ID
  approvalTime: '',
  description: ''
})

const fetchRecordDetail = async () => {
  loading.value = true
  try {
    const res = await getMaintainRecordById(id)
    if (res.data.code === 200) {
      record.value = res.data.data.record
      // 初始化编辑表单
      editForm.value = {
        id: record.value.id,
        status: record.value.status,
        approvalId: userStore.info.id || '',
        approvalTime: record.value.approvalTime,
        description: record.value.description
      }
    } else {
      ElMessage.error(res.data.message || '获取维修记录详情失败')
    }
  } catch (error) {
    ElMessage.error('获取维修记录详情失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const handleApproval = async () => {
  try {
    loading.value = true
    const res = await approvalMaintainRecord(editForm.value)
    if (res.data.code === 200) {
      ElMessage.success('审批成功')
      editDrawerVisible.value = false
      // 添加短暂延迟让用户看到成功消息，然后返回上一页
      setTimeout(() => {
        router.go(-1)
      }, 800)
    } else {
      ElMessage.error(res.data.message || '审批失败')
    }
  } catch (error) {
    ElMessage.error('审批失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const showEditDrawer = () => {
  if (record.value.approvalTime) {
    ElMessage.info('该工单已完成审批，不能重复审批')
    return
  }
  editDrawerVisible.value = true
  editForm.value.operatorId = record.value.operatorId
}

const goBack = () => {
  router.go(-1)
}

onMounted(() => {
  fetchRecordDetail()
  
})
</script>

<template>
  <el-card class="page-container" v-loading="loading">
    <template #header>
      <div class="header">
        <span>维修审批详情</span>
        <div>
          <el-button type="primary" @click="showEditDrawer" v-if="record && !record.approvalTime">审批</el-button>
          <el-button @click="goBack">返回</el-button>
        </div>
      </div>
    </template>

    <div v-if="record">
      <el-descriptions title="基本信息" border :column="2">
        <el-descriptions-item label="ID">{{ record.id }}</el-descriptions-item>
        <el-descriptions-item label="设备ID">{{ record.deviceId }}</el-descriptions-item>
        <el-descriptions-item label="维修类型">{{ record.maintenanceType }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ record.startTime }}</el-descriptions-item>
        <el-descriptions-item label="结束时间">{{ record.endTime }}</el-descriptions-item>
        <el-descriptions-item label="操作员ID">{{ record.operatorId }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ record.description }}</el-descriptions-item>
        <el-descriptions-item label="处理过程">{{ record.repairProcess || '暂无' }}</el-descriptions-item>
        <el-descriptions-item label="解决方案">{{ record.solution || '暂无' }}</el-descriptions-item>
        <el-descriptions-item label="审批状态">
          <el-tag :type="record.approvalTime ? (record.status === '已拒绝' ? 'danger' : 'success') : 'warning'">
            {{ record.approvalTime ? (record.status === '已拒绝' ? '已拒绝' : '已通过') : '待审批' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="审批员ID">{{ record.approvalId || '未审批' }}</el-descriptions-item>
        <el-descriptions-item label="审批时间">{{ record.approvalTime || '未审批' }}</el-descriptions-item>
        <el-descriptions-item label="维修工ID">{{ record.miantainId }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-else style="text-align:center; padding:20px;">
      暂无详情数据
    </div>

    <!-- 审批抽屉 -->
    <el-drawer v-model="editDrawerVisible" title="审批维修记录" direction="rtl" size="40%">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="审批状态">
          <el-select v-model="editForm.status" placeholder="请选择审批状态">
            <el-option label="通过" value="已通过" />
            <el-option label="拒绝" value="已拒绝" />
          </el-select>
        </el-form-item>
        <el-form-item label="请求人ID">
          <el-input v-model="editForm.operatorId" disabled />
        </el-form-item>
        <el-form-item label="审批人ID">
          <el-input v-model="editForm.approvalId" disabled />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleApproval">提交审批</el-button>
          <el-button @click="editDrawerVisible = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-drawer>
  </el-card>
</template>

<style lang="scss" scoped>
.page-container {
  min-height: 100%;
  box-sizing: border-box;

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
}
</style>
