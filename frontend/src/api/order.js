import request from '@/utils/request.js'

export const postMaintainOrder = (maintainRecord) => {
    return request.post('/deviceMaintain/getMaintainOrder', maintainRecord)
  }
  

export const getMaintainOrderById=(miantainData)=>{
    return request.post('/deviceMaintain/getMaintainOrder',miantainData)

}

