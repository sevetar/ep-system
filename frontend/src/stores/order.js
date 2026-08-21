//定义store
import {defineStore} from 'pinia'
import {ref} from 'vue'


export const useOrderStore = defineStore('order',()=>{

    const order = ref('')

 
    const setOrder = (newOrder)=>{
        order.value = newOrder
    }

   
    const removeOrder = ()=>{
        order.value=''
    }

    return {
        order,setOrder,removeOrder
    }
},{
    persist:true//持久化存储
});