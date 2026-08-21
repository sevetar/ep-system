
import axios from 'axios';
import { ElMessage } from 'element-plus'
const baseURL = import.meta.env.VITE_JAVA_API_BASE || '/api';
const instance = axios.create({ baseURL })
import { useTokenStore } from '../stores/token';

//添加请求拦截器
instance.interceptors.request.use(
    (config)=>{
        //请求前的回调
        //添加token
        const tokenStore = useTokenStore();
        //判断有没有token
        if(tokenStore.token){
            config.headers.Authorization = tokenStore.token
        }
        return config;
    },
    (err)=>{
        //请求错误的回调
        return Promise.reject(err)
    }
)
/* import {useRouter} from 'vue-router'
const router = useRouter(); */

import router from '@/router'
// 添加响应拦截器
instance.interceptors.response.use(
    result => {
        //判断业务状态码
        if(result.data?.code===200){
            return result;
        }
        if(result.data.code===401){
            ElMessage.error('请先登录')
            router.push('/login')
        }
        if(result.data.code===501){
            ElMessage.error('用户名或密码错误')
        }
        //操作失败
        //alert(result.data.msg?result.data.msg:'服务异常')
        ElMessage.error(result.data?.message || result.data?.msg || '服务异常')
        //异步操作的状态转换为失败
        return Promise.reject(result.data)
        
    },
    err => {
        //判断响应状态码,如果为401,则证明未登录,提示请登录,并跳转到登录页面
        if(err.response?.status===401){
            ElMessage.error('请先登录')
            router.push('/login')
        } else if (err.code === 'ECONNABORTED') {
            ElMessage.error('请求超时，请稍后重试')
        } else {
            ElMessage.error(err.response?.data?.message || '服务暂时不可用')
        }
        return Promise.reject(err);//异步的状态转化成失败的状态
    }
)
export default instance;


