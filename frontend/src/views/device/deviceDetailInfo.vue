<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deviceTrueDetailService,
  deviceUpdateService,
  deviceTrueDeleteService,
  maintainRecordCreateService,
} from '@/api/device'
import { addDeviceToUser, getDevicesByUserId } from '@/api/user'
import useUserInfoStore from '@/stores/userInfo'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const currentDeviceId = ref(route.params.id || null)
const device = ref({})
const editForm = ref({})
const drawerVisible = ref(false)
const maintainDialogVisible = ref(false)
const bindingDevice = ref(false)
const isOwnedByCurrentUser = ref(false)
const maintainFormRef = ref()
const maintainForm = ref({
  deviceId: currentDeviceId.value,
  maintenanceType: '',
  operatorId: '',
  description: ''
})
const userInfoStore = useUserInfoStore()

const hasPermission = computed(() => {
  const roles = Array.isArray(userInfoStore.role) ? userInfoStore.role : []
  return roles.includes(1)
})

const maintainRules = {
  maintenanceType: [{ required: true, message: '请选择问题类型', trigger: 'change' }],
  description: [
    { required: true, message: '请输入问题描述', trigger: 'blur' },
    { min: 5, max: 500, message: '问题描述需 5-500 个字符', trigger: 'blur' }
  ]
}

const checkOwnership = async () => {
  if (!userInfoStore.info.id || hasPermission.value) return
  try {
    const result = await getDevicesByUserId({
      userId: userInfoStore.info.id,
      pageNum: 1,
      pageSize: 100
    })
    const relations = result.data.data?.items || []
    isOwnedByCurrentUser.value = relations.some(
      relation => String(relation.deviceId) === String(currentDeviceId.value)
    )
  } catch {
    isOwnedByCurrentUser.value = false
  }
}

const fetchDevice = async () => {
  try {
    const res = await deviceTrueDetailService(currentDeviceId.value)
    const data = res.data.data.deviceinstance
    device.value = data
    editForm.value = { ...data }
  } catch (e) {
    ElMessage.error('获取设备详情失败')
  }
}

const openEditDrawer = () => {
  drawerVisible.value = true
}

const closeEditDrawer = () => {
  drawerVisible.value = false
}

const updateDevice = async () => {
  try {
    await deviceUpdateService(editForm.value)
    ElMessage.success('更新成功')
    drawerVisible.value = false
    fetchDevice()
  } catch (e) {
    ElMessage.error('更新失败')
  }
}

const confirmDelete = () => {
  ElMessageBox.confirm(
    '确定要删除这个设备吗？此操作不可撤销！',
    '警告',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    }
  ).then(async () => {
    try {
      await deviceTrueDeleteService(currentDeviceId.value)
      ElMessage.success('删除成功')
    } catch (e) {
      ElMessage.error('删除失败')
    }
  }).catch(() => {
    ElMessage.info('已取消删除')
  })
}

const openMaintainForm = () => {
  if (!isOwnedByCurrentUser.value) {
    ElMessage.warning('请先领用该设备，再为自己的设备发起报修')
    return
  }
  maintainForm.value.deviceId = currentDeviceId.value
  maintainDialogVisible.value = true
}

const closeMaintainForm = () => {
  maintainDialogVisible.value = false
}

const submitMaintainRecord = async () => {
  try {
    const valid = await maintainFormRef.value?.validate().catch(() => false)
    if (!valid) return
    maintainForm.value.operatorId = userInfoStore.info.id
    await maintainRecordCreateService(maintainForm.value)
    maintainDialogVisible.value = false
    await ElMessageBox.alert(
      '报修单已创建，当前状态为“待审批”。管理员审批通过后，才会进入维修人员领取或智能派单阶段。',
      '报修提交成功',
      { confirmButtonText: '查看我的工单', type: 'success' }
    )
    await router.push('/user/order')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error('问题提交失败')
  }
}

const goBack = () => {
  router.go(-1)
}

// 🆕 用户申请设备绑定
const applyForDevice = async () => {
  bindingDevice.value = true
  try {
    const params = {
      userId: userInfoStore.info.id,
      deviceId: currentDeviceId.value
    }
    const res = await addDeviceToUser(params)
    if (res.data.data.alreadyBound) {
      ElMessage.info('该设备已在“我的设备”中')
      isOwnedByCurrentUser.value = true
    } else if (res.data.data.flag) {
      isOwnedByCurrentUser.value = true
      await fetchDevice()
      await ElMessageBox.alert(
        '设备已绑定到当前账号，现在可以在“我的设备”中查看，也可直接为该设备发起报修。',
        '领用成功',
        { confirmButtonText: '知道了', type: 'success' }
      )
    } else {
      ElMessage.warning(res.data.message || '设备领用失败')
    }
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error('设备领用失败')
  } finally {
    bindingDevice.value = false
  }
}

onMounted(async () => {
  await Promise.all([fetchDevice(), checkOwnership()])
  if (route.query.report === '1' && isOwnedByCurrentUser.value) {
    openMaintainForm()
  }
})
</script>

<template>
  <div class="device-detail-container">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>设备详细信息</span>
          <div style="float: right;">
            <el-button v-if="hasPermission" type="primary" size="small" @click="openEditDrawer">编辑</el-button>
            <el-button v-if="hasPermission" type="danger" size="small" @click="confirmDelete">删除</el-button>
            <el-button
              v-if="!hasPermission && !isOwnedByCurrentUser"
              type="success"
              size="small"
              :loading="bindingDevice"
              @click="applyForDevice"
            >领用设备</el-button>
            <el-tag v-else-if="!hasPermission" type="success">我的设备</el-tag>
            <el-button size="small" @click="goBack">返回</el-button>
          </div>
        </div>
      </template>

      <el-descriptions title="设备实例" :column="2" border size="default">
        <el-descriptions-item label="设备ID">{{ device.id }}</el-descriptions-item>
        <el-descriptions-item label="模型ID">{{ device.modelId }}</el-descriptions-item>
        <el-descriptions-item label="序列号">{{ device.serialNumber }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="device.status === 1 ? 'success' : 'info'">
            {{ device.status === 1 ? '在线' : '离线' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="位置">{{ device.location }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ device.createAt }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-drawer title="编辑设备信息" v-model="drawerVisible" size="40%">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="模型ID">
          <el-input v-model="editForm.modelId" />
        </el-form-item>
        <el-form-item label="序列号">
          <el-input v-model="editForm.serialNumber" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" placeholder="选择状态">
            <el-option label="在线" :value="1" />
            <el-option label="离线" :value="0" />
          </el-select>
        </el-form-item>
        <el-form-item label="位置">
          <el-input v-model="editForm.location" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeEditDrawer">取消</el-button>
        <el-button type="primary" @click="updateDevice">保存</el-button>
      </template>
    </el-drawer>

    <el-alert
      v-if="isOwnedByCurrentUser"
      title="可以为自己领用的设备发起报修；提交后需要管理员审批"
      type="info"
      :closable="false"
      show-icon
      class="report-tip"
    />
    <el-button v-if="isOwnedByCurrentUser" type="primary" @click="openMaintainForm">为该设备报修</el-button>

    <el-dialog title="提交问题" v-model="maintainDialogVisible" width="40%">
      <el-form ref="maintainFormRef" :model="maintainForm" :rules="maintainRules" label-width="100px">
        <el-form-item label="问题类型" prop="maintenanceType">
          <el-select v-model="maintainForm.maintenanceType" placeholder="选择问题类型">
            <el-option label="维修" :value="'维修'" />
            <el-option label="保养" :value="'保养'" />
            <el-option label="升级" :value="'升级'" />
          </el-select>
        </el-form-item>
        <el-form-item label="问题描述" prop="description">
          <el-input type="textarea" v-model="maintainForm.description" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeMaintainForm">取消</el-button>
        <el-button type="primary" @click="submitMaintainRecord">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.device-detail-container {
  padding: 20px;
}

.card-header {
  font-size: 18px;
  font-weight: bold;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.el-tag {
  font-size: 14px;
}

.report-tip {
  margin: 20px 0 12px;
}
</style>
