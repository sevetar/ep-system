<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getMaintainRecord } from '@/api/device.js'

const router = useRouter()
const records = ref([])
const loading = ref(false)
const pageNum = ref(1)
const pageSize = ref(10)
const total = ref(0)
const keyword = ref('')
const status = ref('')

const statusOptions = ['待审批', '已通过', '已拒绝', '待领取', '维护中', '已完成']

const fetchRecords = async () => {
  loading.value = true
  try {
    const params = { pageNum: pageNum.value, pageSize: pageSize.value }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (status.value) params.status = status.value
    const result = await getMaintainRecord(params)
    records.value = result.data.data.records || []
    total.value = result.data.data.total || 0
  } catch (error) {
    ElMessage.error('获取工单历史失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const search = () => {
  pageNum.value = 1
  fetchRecords()
}

const reset = () => {
  keyword.value = ''
  status.value = ''
  search()
}

onMounted(fetchRecords)
</script>

<template>
  <el-card class="page-container">
    <template #header>
      <div class="header">
        <div>
          <div>工单历史</div>
          <small>查看全部工单的问题、审批、处理过程和解决方案</small>
        </div>
        <div class="filters">
          <el-input
            v-model="keyword"
            clearable
            placeholder="工单 ID/设备 ID/问题/处理过程/方案"
            @keyup.enter="search"
          />
          <el-select v-model="status" clearable placeholder="全部状态" @change="search">
            <el-option v-for="item in statusOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="records" style="width: 100%">
      <el-table-column label="工单 ID" prop="id" width="100">
        <template #default="{ row }">
          <el-link type="primary" @click="router.push(`/admin/deviceApprovalDetail/${row.id}`)">{{ row.id }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="设备 ID" prop="deviceId" width="110" />
      <el-table-column label="类型" prop="maintenanceType" width="100" />
      <el-table-column label="问题" prop="description" min-width="180" show-overflow-tooltip />
      <el-table-column label="处理过程" prop="repairProcess" min-width="180" show-overflow-tooltip />
      <el-table-column label="解决方案" prop="solution" min-width="180" show-overflow-tooltip />
      <el-table-column label="状态" prop="status" width="100" />
      <el-table-column label="提交时间" prop="startTime" min-width="170" />
      <el-table-column label="完成时间" prop="endTime" min-width="170" />
    </el-table>

    <el-pagination
      v-model:current-page="pageNum"
      v-model:page-size="pageSize"
      :page-sizes="[5, 10, 20, 50]"
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
      background
      class="pagination"
      @size-change="fetchRecords"
      @current-change="fetchRecords"
    />
  </el-card>
</template>

<style scoped>
.page-container { min-height: 100%; box-sizing: border-box; }
.header { display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.header small { color: var(--el-text-color-secondary); }
.filters { display: grid; grid-template-columns: minmax(260px, 1fr) 140px auto auto; gap: 8px; }
.pagination { margin-top: 20px; justify-content: flex-end; }
</style>
