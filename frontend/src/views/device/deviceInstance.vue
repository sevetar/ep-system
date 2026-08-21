<script setup>
import { Edit, Delete, Search } from '@element-plus/icons-vue'
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deviceBriefService, deviceListService, deviceUpdateService, deviceTrueDeleteService } from '@/api/device.js'
import { useRouter, useRoute } from 'vue-router'
import useUserInfoStore from '@/stores/userInfo'
import { searchDevice } from '@/api/search.js'

const roles = useUserInfoStore().role
const router = useRouter()
const route = useRoute()

const devices = ref([])
const loading = ref(false)
const title = ref('设备实例管理')
const searchKeyword = ref('')
const modelOptions = ref([])
const formRef = ref()

const form = ref({
  modelId: '',
  serialNumber: '',
  status: 1,
  location: ''
})

const drawerVisible = ref(false)
const isEditMode = ref(false)
const currentEditId = ref(null)

const normalizeId = (value) => {
  if (value === undefined || value === null || value === '') return null
  const id = Number(value)
  return Number.isInteger(id) ? id : null
}

const currentModelId = ref(normalizeId(route.params.id))

const pageNum = ref(1)
const total = ref(0)
const pageSize = ref(3)

const formRules = {
  modelId: [{ required: true, message: '请选择设备型号', trigger: 'change' }],
  serialNumber: [{ required: true, message: '请输入设备序列号', trigger: 'blur' }]
}

const openNewDrawer = () => {
  isEditMode.value = false
  form.value = {
    modelId: currentModelId.value ?? '',
    serialNumber: '',
    status: 1,
    location: ''
  }
  drawerVisible.value = true
}

const openEditDrawer = (row) => {
  isEditMode.value = true
  currentEditId.value = row.id
  form.value = {
    id: row.id,
    modelId: row.modelId,
    serialNumber: row.serialNumber,
    status: row.status,
    location: row.location
  }
  drawerVisible.value = true
}

const closeDrawer = () => {
  drawerVisible.value = false
}

const saveDevice = async () => {
  try {
    await formRef.value.validate()
    const deviceData = {
      ...form.value,
      modelId: Number(form.value.modelId)
    }
    await deviceUpdateService(deviceData)
    ElMessage.success(isEditMode.value ? '保存成功' : '创建成功')
    drawerVisible.value = false
    deviceList()
  } catch (error) {
    console.error(error)
  }
}

const deleteDevice = async (id) => {
  try {
    await ElMessageBox.confirm('确认要删除该设备吗？', '温馨提示', {
      type: 'warning'
    })
    await deviceTrueDeleteService(id)
    ElMessage.success('删除成功')
    deviceList()
  } catch (error) {
    ElMessage.info('取消删除')
  }
}

const onSizeChange = (size) => {
  pageSize.value = size
  deviceList()
}

const onCurrentChange = (num) => {
  pageNum.value = num
  deviceList()
}

const deviceList = async () => {
  if (searchKeyword.value.trim() !== '') return
  loading.value = true
  try {
    const params = {
      pageNum: pageNum.value,
      pageSize: pageSize.value
    }
    if (currentModelId.value !== null) {
      params.id = currentModelId.value
    }
    const result = await deviceBriefService(params)
    devices.value = result.data.data.items
    total.value = result.data.data.total
  } catch (error) {
    ElMessage.error('获取设备列表失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

const loadModelOptions = async () => {
  try {
    const result = await deviceListService({ pageNum: 1, pageSize: 100 })
    modelOptions.value = result.data.data.items ?? []
  } catch (error) {
    ElMessage.error('获取设备型号失败')
    console.error(error)
  }
}

const formatStatus = (status) => {
  if (status === undefined || status === null) return '未知'
  if (typeof status === 'boolean') return status ? '在线' : '离线'
  if (typeof status === 'number') return status === 1 ? '在线' : '离线'
  return status.toString()
}

const getStatusTagType = (status) => {
  const formatted = formatStatus(status)
  if (formatted === '在线') return 'success'
  if (formatted === '离线') return 'danger'
  return 'info'
}

watch(() => route.params.id, (newId) => {
  currentModelId.value = normalizeId(newId)
  pageNum.value = 1
  deviceList()
})

onMounted(() => {
  loadModelOptions()
  deviceList()
})

const goToDetail = (id) => {
  router.push(`/device/DetailInfo/${id}`)
}

// 搜索功能
const handleSearch = async () => {
  if (!searchKeyword.value.trim()) {
    deviceList()
    return
  }
  loading.value = true
  try {
    const result = await searchDevice(searchKeyword.value.trim())
    const data = result.data.data
    if (data && data.Deviceinstances) {
      devices.value = data.Deviceinstances // 获取设备列表
      total.value = data.Deviceinstances.length // 设置总数
    } else {
      devices.value = []
      total.value = 0
      ElMessage.warning('未找到相关设备')
    }
  } catch (err) {
    ElMessage.error('搜索失败')
    console.error(err)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-card class="page-container">
    <template #header>
      <div class="header">
        <span>{{ title }}</span>
        <div v-if="currentModelId !== null" class="filter-tip">
          当前筛选型号 ID: {{ currentModelId }}
          <el-button link type="primary" @click="router.push('/device/instance')">清除筛选</el-button>
        </div>
        <div class="actions">
          <el-input
            v-model="searchKeyword"
            placeholder="请输入关键词搜索"
            style="width: 200px; margin-right: 10px"
            clearable
            @clear="deviceList"
            @keyup.enter="handleSearch"
          >
            <template #suffix>
              <el-icon @click="handleSearch"><Search /></el-icon>
            </template>
          </el-input>
          <el-button type="primary" @click="openNewDrawer">新增设备</el-button>
          <el-button link type="primary" @click="router.back()">返回上一页</el-button>
        </div>
      </div>
    </template>

    <el-table :data="devices" v-loading="loading" style="width: 100%">
      <el-table-column label="设备ID" prop="id" width="120">
        <template #default="{ row }">
          <el-link type="primary" @click="goToDetail(row.id)">{{ row.id }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="模型ID" prop="modelId" width="120" />
      <el-table-column label="序列号" prop="serialNumber" />
      <el-table-column label="状态" prop="status" width="100">
        <template #default="{ row }">
          <el-tag :type="getStatusTagType(row.status)">
            {{ formatStatus(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="位置" prop="location" />
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button :icon="Edit" circle plain type="primary" @click="openEditDrawer(row)" />
          <el-button :icon="Delete" circle plain type="danger" @click="deleteDevice(row.id)" />
        </template>
      </el-table-column>
    </el-table>

    <el-drawer :title="isEditMode ? '编辑设备信息' : '新增设备'" v-model="drawerVisible" size="40%">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="设备型号" prop="modelId">
          <el-select v-model="form.modelId" placeholder="请选择设备型号" style="width: 100%">
            <el-option
              v-for="model in modelOptions"
              :key="model.id"
              :label="`${model.modelName} (ID: ${model.id})`"
              :value="model.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="序列号" prop="serialNumber">
          <el-input v-model="form.serialNumber" placeholder="请输入序列号" />
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-select v-model="form.status" placeholder="请选择状态">
            <el-option label="在线" :value="1" />
            <el-option label="离线" :value="0" />
          </el-select>
        </el-form-item>
        <el-form-item label="位置" prop="location">
          <el-input v-model="form.location" placeholder="请输入位置" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeDrawer">取消</el-button>
        <el-button type="primary" @click="saveDevice">{{ isEditMode ? '保存' : '添加' }}</el-button>
      </template>
    </el-drawer>

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

    .filter-tip {
      font-size: 14px;
      color: var(--el-text-color-secondary);
      .el-button {
        margin-left: 10px;
      }
    }

    .actions {
      display: flex;
      align-items: center;
    }
  }
}
</style>
