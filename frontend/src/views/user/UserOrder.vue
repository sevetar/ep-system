<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getMyMaintainOrder, getMyRepairOrder, updateMyRepairOrder } from '@/api/user.js'
import { useRouter } from 'vue-router'
import useUserInfoStore from '@/stores/userInfo'

const orders = ref([])
const pageNum = ref(1)
const pageSize = ref(5)
const total = ref(0)

const router = useRouter()
const userStore = useUserInfoStore()
const userId = userStore.info.id

const orderType = ref('maintain') // maintain（发起的）或 repair（维修的）
const completeDialogVisible = ref(false)
const completing = ref(false)
const selectedOrder = ref(null)
const completeFormRef = ref()
const emptyCompleteForm = () => ({
  repairProcess: '',
  solution: '',
  rootCause: '',
  verificationResult: '',
  replacedParts: '',
  knowledgeTags: ''
})
const completeForm = ref(emptyCompleteForm())
const completeRules = {
  repairProcess: [{ required: true, min: 8, message: '请填写至少 8 个字的处理过程', trigger: 'blur' }],
  solution: [{ required: true, min: 8, message: '请填写至少 8 个字的解决方案', trigger: 'blur' }],
  verificationResult: [{ required: true, min: 4, message: '请填写至少 4 个字的修复验证结果', trigger: 'blur' }]
}

const fetchOrders = async () => {
  try {
    let res
    const params = {
      pageNum: pageNum.value,
      pageSize: pageSize.value,
      userId
    }

    if (orderType.value === 'maintain') {
      res = await getMyMaintainOrder(params)
    } else {
      res = await getMyRepairOrder(params)
    }

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

const onOrderTypeChange = (val) => {
  pageNum.value = 1
  fetchOrders()
}

const goToDeviceDetail = (deviceId) => {
  router.push(`/device/DetailInfo/${deviceId}`)
}

// 完成工单
const handleComplete = async (row) => {
  selectedOrder.value = row
  completeForm.value = emptyCompleteForm()
  completeDialogVisible.value = true
}

const submitComplete = async () => {
  try {
    const valid = await completeFormRef.value?.validate().catch(() => false)
    if (!valid) return
    completing.value = true
    const res = await updateMyRepairOrder({
      id: selectedOrder.value.id,
      ...completeForm.value
    })
    if (res.data.code === 200) {
      ElMessage.success('工单已完成')
      if (res.data.data?.knowledgeEventId) {
        ElMessage.info(`知识事件已创建：${res.data.data.knowledgeEventId}`)
      }
      completeDialogVisible.value = false
      fetchOrders()
    } else {
      ElMessage.error(res.data.msg || '更新失败')
    }
  } catch (err) {
    console.error(err)
  } finally {
    completing.value = false
  }
}

onMounted(() => {
  fetchOrders()
})
</script>

<template>
  <el-card class="page-container">
    <template #header>
      <div class="header">
        <span>个人工单管理</span>
        <div class="extra">
          <el-radio-group v-model="orderType" @change="onOrderTypeChange">
            <el-radio-button label="maintain">我发起的工单</el-radio-button>
            <el-radio-button label="repair">我维修的工单</el-radio-button>
          </el-radio-group>
          <el-button type="primary" @click="fetchOrders" style="margin-left: 12px">刷新</el-button>
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
      <el-table-column label="工单问题" prop="description" min-width="180" show-overflow-tooltip />
      <el-table-column label="处理过程" prop="repairProcess" min-width="180" show-overflow-tooltip />
      <el-table-column label="解决方案" prop="solution" min-width="180" show-overflow-tooltip />
      <el-table-column label="修复验证" prop="verificationResult" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" prop="status" />
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <!-- 仅在维修订单中，且状态为“维修中”时可见 -->
          <el-button 
            v-if="orderType === 'repair' && row.status === '维护中'"
            size="small" 
            type="success" 
            @click="handleComplete(row)"
            style="margin-left: 8px"
          >
            完成
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="completeDialogVisible" title="完成维修工单并沉淀案例知识" width="620px">
      <el-alert
        :title="`工单问题：${selectedOrder?.description || '未填写'}`"
        type="info"
        :closable="false"
        class="completion-alert"
      />
      <el-form ref="completeFormRef" :model="completeForm" :rules="completeRules" label-position="top">
        <el-form-item label="处理过程" prop="repairProcess">
          <el-input v-model="completeForm.repairProcess" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="说明检查、定位和处理步骤（至少 8 个字）" />
        </el-form-item>
        <el-form-item label="解决方案" prop="solution">
          <el-input v-model="completeForm.solution" type="textarea" :rows="3" maxlength="2000" show-word-limit placeholder="说明最终采取的解决方案（至少 8 个字）" />
        </el-form-item>
        <el-form-item label="根因分析（建议填写）" prop="rootCause">
          <el-input v-model="completeForm.rootCause" type="textarea" :rows="2" maxlength="2000" show-word-limit placeholder="说明确认或推测的故障根因" />
        </el-form-item>
        <el-form-item label="修复验证" prop="verificationResult">
          <el-input v-model="completeForm.verificationResult" type="textarea" :rows="2" maxlength="2000" show-word-limit placeholder="例如：连续运行 30 分钟，温度和告警恢复正常" />
        </el-form-item>
        <el-form-item label="更换部件" prop="replacedParts">
          <el-input v-model="completeForm.replacedParts" maxlength="1000" placeholder="没有更换可留空" />
        </el-form-item>
        <el-form-item label="知识标签" prop="knowledgeTags">
          <el-input v-model="completeForm.knowledgeTags" maxlength="1000" placeholder="逗号分隔，例如：不制冷,制冷剂泄漏" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="completeDialogVisible = false">取消</el-button>
        <el-button type="success" :loading="completing" @click="submitComplete">确认完成</el-button>
      </template>
    </el-dialog>

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
.completion-alert {
  margin-bottom: 16px;
}
</style>
