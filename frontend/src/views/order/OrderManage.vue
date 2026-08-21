<script setup>
import { onMounted, ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { getClaimableMaintainRecords } from '@/api/device.js'
import { postMaintainOrder } from '@/api/order.js'
import { useRouter } from 'vue-router'
import useUserInfoStore from '@/stores/userInfo'
import { subscribe, unsubscribe } from '@/utils/websocket'

const orders = ref([])
const pageNum = ref(1)
const pageSize = ref(5)
const total = ref(0)

const router = useRouter()
const userStore = useUserInfoStore()
const maintainId = userStore.info.id
const isClaimable = row => ['已通过', '待领取'].includes(row.status) && row.miantainId == null

// 加载分页工单数据
const fetchOrders = async () => {
  try {
    const res = await getClaimableMaintainRecords({
      pageNum: pageNum.value,
      pageSize: pageSize.value
    })
    const allOrders = res.data.data.records || []
    orders.value = allOrders
    total.value = res.data.data.total
  } catch (err) {
    ElMessage.error('获取工单失败')
  }
}

const onSizeChange = (size) => {
  pageSize.value = size
  fetchOrders()
}

const onCurrentChange = (num) => {
  pageNum.value = num
  fetchOrders()
}

const goToDeviceDetail = (deviceId) => {
  router.push(`/device/DetailInfo/${deviceId}`)
}

// 点击按钮时先检查状态
const handleClick = (row) => {
  if (!isClaimable(row)) {
    ElMessage.warning('当前状态不可接单')
    return
  }
  getOrder(row)
}

// 接单操作
const getOrder = async (row) => {
  const updateData = {
    ...row,
    miantainId:maintainId,
    status: '维护中'
  }

  try {
    const res = await postMaintainOrder(updateData)
    if (res.data.code === 200) {
      ElMessage.success('工单接单成功')
      fetchOrders()
    } else {
      ElMessage.error(res.data.msg || '工单接单失败')
    }
  } catch (error) {
    ElMessage.error('请求出错，接单失败')
  }
}

// WebSocket 消息刷新
const handleOrderMessage = (msg) => {
  if (msg.type === 'refresh') {
    ElMessage.success('有新工单内容，数据已刷新！')
    fetchOrders()
  }
}

onMounted(() => {
  fetchOrders()
  subscribe('/topic/repairMan', handleOrderMessage)
})

onBeforeUnmount(() => {
  unsubscribe(handleOrderMessage)
})
</script>

<template>
  <el-card class="page-container">
    <template #header>
      <div class="header">
        <div>
          <div>接单平台</div>
          <small class="header-tip">仅展示审批通过且尚未被领取的工单</small>
        </div>
        <div class="extra">
          <el-button type="primary" @click="fetchOrders">刷新</el-button>
        </div>
      </div>
    </template>

    <el-table :data="orders" style="width: 100%">
      <el-table-column label="工单ID" prop="id" />
      <el-table-column label="设备ID">
        <template #default="{ row }">
          <el-link type="primary" @click="goToDeviceDetail(row.deviceId)">
            {{ row.deviceId }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column label="维护类型" prop="maintenanceType" />
      <el-table-column label="工单问题" prop="description" min-width="220" show-overflow-tooltip />
      <el-table-column label="状态" prop="status" />
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-tooltip
            content="只有已通过的工单才能接单"
            :disabled="isClaimable(row)"
          >
            <el-button 
              size="small" 
              type="primary" 
              :disabled="!isClaimable(row)" 
              @click="handleClick(row)"
            >
              获取订单
            </el-button>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="pageNum"
      v-model:page-size="pageSize"
      :page-sizes="[3, 5, 10, 20]"
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
      @size-change="onSizeChange"
      @current-change="onCurrentChange"
      background
      style="margin-top: 20px; justify-content: flex-end"
    />
  </el-card>
</template>

<style scoped>
.page-container {
  min-height: 100%;
  box-sizing: border-box;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-tip {
  color: var(--el-text-color-secondary);
}
</style>
