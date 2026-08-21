<script setup>
import { ref, onMounted, reactive } from 'vue';
import { Edit, Delete } from '@element-plus/icons-vue';
import { deviceCategoryAddService, deviceCategoryDeleteService, deviceCategoryUpdateService, deviceCategoryListService } from '../../api/device';
import { ElMessage } from 'element-plus'
import useUserInfoStore from '../../stores/userInfo';

const roles=useUserInfoStore().role;

// 定义响应式数据
const category = reactive({
    categories: []
});
//控制添加分类弹窗
const dialogVisible = ref(false)
// 获取分类数据的方法
const deviceCategoryList = async () => {
    let { data } = await deviceCategoryListService(); // 调用服务获取数据
    // 确保返回的数据结构正确
    category.categories = data.data.categories
};
//添加分类数据模型
const categoryModel = ref({
    categoryName: '',
    description: ''
})

// 页面加载时调用数据加载方法
onMounted(() => {
    deviceCategoryList();
   
});

//添加分类表单校验
const rules = {
    categoryName: [
        { required: true, message: '请输入分类名称', trigger: 'blur' },
    ],
    description: [
        { required: true, message: '请输入分类描述', trigger: 'blur' },
    ]
}
//访问后台，添加文章分类
const addCategory = async ()=>{
    let result = await deviceCategoryAddService(categoryModel.value);
    ElMessage.success(result.message? result.message:'添加成功')
    //隐藏弹窗
    dialogVisible.value = false
    //再次访问后台接口，查询所有分类
    deviceCategoryList();
}
const title=ref('')
//清空模型的数据
const clearData = () => {
    categoryModel.value.categoryName = '';
    categoryModel.value.description = '';
}
const showDialog = (row) => {
    dialogVisible.value = true; title.value = '编辑分类'
    //数据拷贝
    categoryModel.value.categoryName = row.categoryName;
    categoryModel.value.description = row.description;
    //扩展id属性,将来需要传递给后台,完成分类的修改
    categoryModel.value.id = row.id
}
//修改分类
const updateCategory=async ()=>{
    let result = await deviceCategoryUpdateService(categoryModel.value)
    ElMessage.success(result.message? result.message:'修改成功')
    //隐藏弹窗
    dialogVisible.value=false
    deviceCategoryList();
}
//删除分类
import {ElMessageBox} from 'element-plus'
const deleteCategory = (row) => {
    //提示用户  确认框

    ElMessageBox.confirm(
        '你确认要删除该分类信息吗?',
        '温馨提示',
        {
            confirmButtonText: '确认',
            cancelButtonText: '取消',
            type: 'warning',
        }
    )
        .then(async () => {
            //调用接口
            let result = await deviceCategoryDeleteService(row.id);
            ElMessage({
                type: 'success',
                message: '删除成功',
            })
            //刷新列表
            deviceCategoryList();
        })
        .catch(() => {
            ElMessage({
                type: 'info',
                message: '用户取消了删除',
            })
        })
}
</script>

<template>
    <el-card class="page-container">
        <template #header>
            <div class="header">
                <span>设备分类</span>
                <div class="extra">
                    <el-button type="primary" @click="dialogVisible=true;title='添加分类'">添加分类</el-button>
                </div>
            </div>
        </template>

        <!-- 仅在数据加载完成并且有数据时才渲染表格 -->
        <el-table :data="category.categories" style="width: 100%">
            <el-table-column label="序号" width="100" type="index"> </el-table-column>
            <el-table-column label="分类名称" prop="categoryName"></el-table-column>
            <el-table-column label="分类描述" prop="description"></el-table-column>
            <el-table-column label="操作" width="100">
                <template #default="{ row }">
                    <!-- <el-button :icon="Edit" circle plain type="primary" @click="dialogVisible=true,title='编辑分类'"></el-button>
                    <el-button :icon="Delete" circle plain type="danger"></el-button> -->
                    <el-button :icon="Edit" circle plain type="primary" @click="showDialog(row)"></el-button>
                    <el-button :icon="Delete" circle plain type="danger" @click="deleteCategory(row)"></el-button>
                </template>
            </el-table-column>
            <!-- 当数据为空时显示占位 -->
            <template #empty>
                <el-empty description="没有数据" />
            </template>
        </el-table>

        <!-- 添加分类弹窗 -->
        <el-dialog v-model="dialogVisible" :title="title" width="30%">
            <el-form :model="categoryModel" :rules="rules" label-width="100px" style="padding-right: 30px">
                <el-form-item label="分类名称" prop="categoryName">
                    <el-input v-model="categoryModel.categoryName" minlength="1" maxlength="10"></el-input>
                </el-form-item>
                <el-form-item label="分类描述" prop="description">
                    <el-input v-model="categoryModel.description" minlength="1" maxlength="15"></el-input>
                </el-form-item>
            </el-form>
            <template #footer>
                <span class="dialog-footer">
                    <el-button @click="dialogVisible = false">取消</el-button>
                    <!-- <el-button type="primary" @click="addCategory"> 确认 </el-button> -->
                    <el-button type="primary" @click="title == '添加分类' ? addCategory() : updateCategory()"> 确认 </el-button>
                </span>
            </template>
        </el-dialog>
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




