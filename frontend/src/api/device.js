import request from '@/utils/request.js'


//设别分类的crud
export const deviceCategoryListService = ()=>{
    return request.get('/device/category/list')
}
export const deviceCategoryAddService = (devicecategory)=>{
    return request.post('/device/category/add',devicecategory)
}
export const deviceCategoryDeleteService = (id)=>{
    return request.get('/device/category/delete',{params:{id:id}})
}
export const deviceCategoryUpdateService = (devicecategory) => {
    return request.post('/device/category/update', devicecategory, {
      headers: {
        'Content-Type': 'application/json' // 明确设置请求头
      }
    });
  };

//设备的crud
//设备列表查询
export const deviceListService = (params)=>{
    return  request.get('/deviceModel/getInfoList',{params:params})
}
//设备添加及修改
export const deviceAddService = (devicemodel)=>{
    return request.post('/deviceModel/addDeviceModel',devicemodel);

}
export const deviceDeleteService = (id) => {
    return request.get('/deviceModel/deleteDeviceModel?id='+id)
}
export const deviceDetailService = (params)=>{
    return  request.get('/deviceModel/getDeviceModelDetailInfo',{params:params})
}

//设备简要的查询
export const deviceBriefService = (params) => {
    return request.get('/deviceInstance/getBriefInfoList', { params });
}

//设备具体详情的查询
export const deviceTrueDetailService = (id) => {
    return request.get(`/deviceInstance/getTrueDetailInfoList/${id}`);
}

export const deviceUpdateService = (deviceInstance) => {
    return request.post('/deviceInstance/updateDeviceInstance',deviceInstance);
}

export const deviceTrueDeleteService = (id) => {
    return request.get(`/deviceInstance/deviceTrueDeleteService/${id}`);
}
export const maintainRecordCreateService = (maintainRecord) => {
    return request.post('/deviceMaintain/createMaintainRecord',maintainRecord);
}


//获取维修记录
export const getMaintainRecord = (params) => {
    return request.get('/deviceMaintain/getMaintainRecord', { params })
  }

export const getClaimableMaintainRecords = (params) => {
    return request.get('/deviceMaintain/getClaimableMaintainRecords', { params })
}

export const getApprovalRecords = (params) => {
    return request.get('/deviceMaintain/getApprovalRecords', { params })
}
  

export const getMaintainRecordById=(id)=>{
    return request.get(`/deviceMaintain/getMaintainRecordById?id=${id}`)

}

//审批用户工单
export const approvalMaintainRecord=(maintainRecord)=>{
    return request.post('/deviceMaintain/approvalMaintainRecord',maintainRecord)
}

// 管理员通过 Java 业务域触发异步自动派单，由 Java 鉴权并写入 Outbox。
export const triggerAutoDispatch = (orderId, idempotencyKey) => {
    return request.post(`/deviceMaintain/${encodeURIComponent(orderId)}/auto-dispatch`, null, {
        headers: { 'Idempotency-Key': idempotencyKey }
    })
}


