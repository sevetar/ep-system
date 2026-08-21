import {defineStore} from 'pinia'
import {ref} from 'vue'
const useUserInfoStore = defineStore('userInfo',()=>{
    //定义状态相关的内容

    const info = ref({})
    const role=ref([])

    const setRole = (newRole)=>{
        role.value = newRole
    }

    const removeRole = ()=>{
        role.value = []
    }

    const setInfo = (newInfo)=>{
        info.value = newInfo
    }


    const removeInfo = ()=>{
        info.value = {}
    }

    return { info, setInfo, removeInfo, role, setRole, removeRole }


},{persist:true})

export default useUserInfoStore;