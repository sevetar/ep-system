<script setup>
import {
    Edit,
    Delete
} from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ElMessageBox } from 'element-plus'
import { deviceCategoryListService, deviceListService, deviceAddService, deviceDeleteService, deviceDetailService } from '@/api/device.js'
import useUserInfoStore from '@/stores/userInfo'
const roles = useUserInfoStore().role;

// 设备分类数据模型
const categorys = ref([])

// 用户搜索时选中的分类id
const categoryId = ref('')

// 设备列表数据模型
const devices = ref([])
const title = ref('')

// 分页条数据模型
const pageNum = ref(1) // 当前页
const total = ref(20) // 总条数
const pageSize = ref(3) // 每页条数

const onSizeChange = (size) => {
    pageSize.value = size
    deviceList()
}

const onCurrentChange = (num) => {
    pageNum.value = num
    deviceList()
}

// 查询所有分类
const fetchDeviceCategories = async () => {
    let result = await deviceCategoryListService()
    categorys.value = result.data.data.categories
    categorys.value.unshift({
        id: '',
        categoryName: '全部分类'
    })
}

// 获取设备模型列表数据
const deviceList = async () => {
    let params = {
        pageNum: pageNum.value,
        pageSize: pageSize.value,
        categoryId: categoryId.value || null
    }
    let result = await deviceListService(params)
    devices.value = result.data.data.items
    total.value = result.data.data.total
}

// 控制抽屉是否显示
const visibleDrawer = ref(false)

// 添加表单数据模型
const deviceModel = ref({
    categoryId: '',
    modelName: '',
    description: '',
    image: ''
})

// 上传成功的回调函数
const uploadSuccess = (result) => {
    deviceModel.value.image = result.data.url
}

// 添加设备模型
const addDevice = async () => {
    let result = await deviceAddService(deviceModel.value)
    ElMessage.success(result.msg || '添加成功')
    visibleDrawer.value = false
    deviceList()
}

// 显示编辑抽屉
const showDialog = (row) => {
    visibleDrawer.value = true
    title.value = '编辑设备模型'
    deviceModel.value = { ...row }
}

// 删除设备模型
const deleteDevice = (row) => {
    ElMessageBox.confirm(
        '你确认要删除该设备模型吗?',
        '温馨提示',
        {
            confirmButtonText: '确认',
            cancelButtonText: '取消',
            type: 'warning'
        }
    )
        .then(async () => {
            let result = await deviceDeleteService(row.id)
            ElMessage.success('删除成功')
            deviceList()
        })
        .catch(() => {
            ElMessage.info('用户取消了删除')
        })
}

onMounted(() => {
    fetchDeviceCategories()
    deviceList()
})

import { useRouter } from 'vue-router'

const router = useRouter()

// 跳转到设备实例页面
const goToInstance = (id) => {
    router.push(`/device/instance/${id}`)
}
</script>

<template>
    <el-card class="page-container">
        <template #header>
            <div class="header">
                <span>设备模型管理</span>
                <div class="extra">
                    <el-button v-if="roles.includes(1)" type="primary" @click="visibleDrawer = true; title = '添加设备模型'">添加设备模型</el-button>
                </div>
            </div>
        </template>

        <!-- 搜索表单 -->
        <el-form inline>
            <el-form-item label="分类：">
                <el-select placeholder="请选择" v-model="categoryId">
                    <el-option v-for="c in categorys" :key="c.id" :label="c.categoryName" :value="c.id" />
                </el-select>
            </el-form-item>
            <el-form-item>
                <el-button type="primary" @click="deviceList">搜索</el-button>
                <el-button @click="categoryId = ''">重置</el-button>
            </el-form-item>
        </el-form>

        <!-- 设备模型列表 -->
        <el-table :data="devices" style="width: 100%">
            <el-table-column label="设备模型名称" prop="modelName">
                <template #default="{ row }">
                    <el-link type="primary" @click="goToInstance(row.id)">{{ row.id }}{{ row.modelName }}</el-link>
                </template>
            </el-table-column>
            <el-table-column label="图片" width="200">
                <template #default="{ row }">
                    <img v-if="row.image" :src="row.image" alt="设备图片" class="cover-img" />
                    <span v-else>暂无图片</span>
                </template>
            </el-table-column>
            <el-table-column label="分类" prop="categoryName" />
            <el-table-column label="描述" prop="description" />
            <el-table-column label="操作" width="100" v-if="roles.includes(1)">
                <template #default="{ row }">
                    <el-button :icon="Edit" circle plain type="primary" @click="showDialog(row)" />
                    <el-button :icon="Delete" circle plain type="danger" @click="deleteDevice(row)" />
                </template>
            </el-table-column>
        </el-table>

        <!-- 分页条 -->
        <el-pagination
            v-model:current-page="pageNum"
            v-model:page-size="pageSize"
            :page-sizes="[3, 5, 10, 15]"
            layout="jumper, total, sizes, prev, pager, next"
            background
            :total="total"
            @size-change="onSizeChange"
            @current-change="onCurrentChange"
            style="margin-top: 20px; justify-content: flex-end"
        />

        <!-- 抽屉 -->
        <el-drawer v-model="visibleDrawer" :title="title" direction="rtl" size="50%">
            <el-form :model="deviceModel" label-width="100px">
                <el-form-item label="设备模型名称">
                    <el-input v-model="deviceModel.modelName" placeholder="请输入设备模型名称" />
                </el-form-item>
                <el-form-item label="分类">
                    <el-select placeholder="请选择" v-model="deviceModel.categoryId">
                        <el-option v-for="c in categorys" :key="c.id" :label="c.categoryName" :value="c.id" />
                    </el-select>
                </el-form-item>
                <el-form-item label="图片">
                    <el-upload
                        class="avatar-uploader"
                        :auto-upload="true"
                        :show-file-list="false"
                        action="http://localhost:8080/file/upload"
                        name="file"
                        :on-success="uploadSuccess"
                    >
                        <img v-if="deviceModel.image" :src="deviceModel.image" class="avatar" />
                        <el-icon v-else class="avatar-uploader-icon">
                            <Plus />
                        </el-icon>
                    </el-upload>
                </el-form-item>
                <el-form-item label="描述">
                    <el-input type="textarea" v-model="deviceModel.description" placeholder="请输入描述" />
                </el-form-item>
                <el-form-item>
                    <el-button type="primary" @click="addDevice">保存</el-button>
                </el-form-item>
            </el-form>
        </el-drawer>
    </el-card>
</template>

<style lang="scss" scoped>
.cover-img {
    width: 100%;
    height: 130px;
    object-fit: cover;
    border-radius: 8px;
    overflow: hidden;
}
.editor {
    width: 100%;
    :deep(.ql-editor) {
        min-height: 200px;
    }
}
.page-container {
    min-height: 100%;
    box-sizing: border-box;
    .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
}
.avatar-uploader {
    :deep() {
        .avatar {
            width: 178px;
            height: 178px;
            display: block;
        }
        .el-upload {
            border: 1px dashed var(--el-border-color);
            border-radius: 6px;
            cursor: pointer;
            position: relative;
            overflow: hidden;
            transition: var(--el-transition-duration-fast);
        }
        .el-upload:hover {
            border-color: var(--el-color-primary);
        }
        .el-icon.avatar-uploader-icon {
            font-size: 28px;
            color: #8c939d;
            width: 178px;
            height: 178px;
            text-align: center;
        }
    }
}
</style>
