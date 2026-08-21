<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDevicesByUserId, removeDeviceFromUser } from '@/api/user.js'
import useUserInfoStore from '@/stores/userInfo'
import { useRouter } from 'vue-router'

const devices = ref([])
const pageNum = ref(1)
const pageSize = ref(5)
const total = ref(0)

const userStore = useUserInfoStore()
const userId = userStore.info.id
const router = useRouter()

const selectDevice = () => {
  router.push('/device/instance')
}

const viewDevice = (deviceId) => {
  router.push(`/device/DetailInfo/${deviceId}`)
}

const reportDevice = (deviceId) => {
  router.push({ path: `/device/DetailInfo/${deviceId}`, query: { report: '1' } })
}

// 获取用户设备列表
const fetchDevices = async () => {
  try {
    const params = {
      pageNum: pageNum.value,
      pageSize: pageSize.value,
      userId,
    }
    const res = await getDevicesByUserId(params)
    const allDevices = res.data.data.items || []
    devices.value = allDevices
    total.value = res.data.data.total
  } catch (err) {
    ElMessage.error('获取设备失败')
  }
}

// 归还设备
const handleReturn = async (deviceId) => {
  try {
    await ElMessageBox.confirm(
      '确定要归还该设备吗？',
      '提示',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    const res = await removeDeviceFromUser({ userId, deviceId })
    if (res.data.code === 200) {
      ElMessage.success('设备已归还')
      fetchDevices()
    } else {
      ElMessage.error(res.data.msg || '归还失败')
    }
  } catch (err) {
    ElMessage.info('已取消操作')
  }
}

const onSizeChange = (size) => {
  pageSize.value = size
  fetchDevices()
}
const onCurrentChange = (num) => {
  pageNum.value = num
  fetchDevices()
}

onMounted(() => {
  fetchDevices()
})
</script>

<template>
  <el-card class="page-container">
    <template #header>
      <div class="header">
        <div>
          <div>我的设备列表</div>
          <div class="header-tip">从设备实例中选择设备，进入详情后点击“领用设备”即可绑定</div>
        </div>
        <div>
          <el-button type="primary" @click="selectDevice">领用设备</el-button>
          <el-button @click="fetchDevices">刷新</el-button>
        </div>
      </div>
    </template>

    <el-table :data="devices" style="width: 100%">
      <el-table-column label="设备ID" prop="deviceId" />
      <el-table-column label="用户ID" prop="userId" />
      <el-table-column label="操作" width="280" align="center">
        <template #default="{ row }">
          <el-button type="primary" link @click="viewDevice(row.deviceId)">查看</el-button>
          <el-button type="warning" link @click="reportDevice(row.deviceId)">发起报修</el-button>
          <el-button 
            type="danger" 
            size="small" 
            @click="handleReturn(row.deviceId)"
          >
            归还设备
          </el-button>
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
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
