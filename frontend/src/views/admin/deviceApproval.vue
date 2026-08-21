<script setup>
import { onMounted, ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { getApprovalRecords } from '@/api/device.js'
import { subscribe, unsubscribe } from '@/utils/websocket'
import useUserInfoStore from '@/stores/userInfo'

const router = useRouter()
const role = useUserInfoStore().role.value

const records = ref([])
const loading = ref(false)
const title = ref('维修审批管理')

const pageNum = ref(1)
const pageSize = ref(3)
const total = ref(0)
const approvalStatus = ref('待审批')

const formatStatus = (status) => {
  return status || '未知'
}

const getStatusTagType = (status) => {
  if (status === '待审批') return 'warning'
  if (status === '已通过') return 'success'
  if (status === '已拒绝') return 'danger'
  return 'info'
}

const fetchData = async () => {
  loading.value = true
  try {
    const params = {
      pageNum: pageNum.value,
      pageSize: pageSize.value
    }
    params.approvalStatus = approvalStatus.value
    const res = await getApprovalRecords(params)
    if (res.data.code === 200) {
      const data = res.data.data
      records.value = data.records || []
      total.value = data.total || 0
    } else {
      ElMessage.error(res.message || '获取维修记录失败')
    }
  } catch (error) {
    ElMessage.error('获取维修记录失败')
    console.error('获取维修记录失败:', error)
  } finally {
    loading.value = false
  }
}

const onSizeChange = (size) => {
  pageSize.value = size
  fetchData()
}

const onCurrentChange = (num) => {
  pageNum.value = num
  fetchData()
}

const goToDetail = (id) => {
  router.push(`/admin/deviceApprovalDetail/${id}`)
}

const onApprovalStatusChange = () => {
  pageNum.value = 1
  fetchData()
}

// 接收消息回调
const handleApprovalMessage = (msg) => {
  if (msg.type === 'refresh') {
    ElMessage.success('有新审批内容，数据已刷新！')
    fetchData()
  }
}

onMounted(() => {
  fetchData()
  // 订阅后端推送的审批刷新消息
  subscribe('/topic/approval', handleApprovalMessage)
})

onBeforeUnmount(() => {
  // 取消订阅，防止内存泄漏
  unsubscribe(handleApprovalMessage)
})
</script>

<template>
  <el-card class="page-container">
    <template #header>
      <div class="header">
        <span>{{ title }}</span>
        <el-radio-group v-model="approvalStatus" @change="onApprovalStatusChange">
          <el-radio-button value="待审批">待审批</el-radio-button>
          <el-radio-button value="已审批">已审批</el-radio-button>
        </el-radio-group>
      </div>
    </template>

    <el-table :data="records" v-loading="loading" style="width: 100%">
      <el-table-column label="设备ID" prop="deviceId" width="120">
        <template #default="{ row }">
          <el-link type="primary" @click="goToDetail(row.id)">
            {{ row.deviceId }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column label="维修类型" prop="maintenanceType" />
      <el-table-column label="开始时间" prop="startTime" />
      <el-table-column label="审批状态">
        <template #default="{ row }">
          <el-tag :type="row.approvalTime ? (row.status === '已拒绝' ? 'danger' : 'success') : 'warning'">
            {{ row.approvalTime ? (row.status === '已拒绝' ? '已拒绝' : '已通过') : '待审批' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="工单进度" prop="status" />
    </el-table>

    <el-pagination
      v-model:current-page="pageNum"
      v-model:page-size="pageSize"
      :page-sizes="[3, 5, 10, 15]"
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
      @size-change="onSizeChange"
      @current-change="onCurrentChange"
      style="margin-top: 20px; justify-content: flex-end"
    />
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
