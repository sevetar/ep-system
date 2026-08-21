import request from '@/utils/request.js'


export const userRegisterService=(registerData)=>{
    const params=new URLSearchParams()
    for(let key in registerData){
        params.append(key,registerData[key]);
    }
    return request.post('/user/register',params);
}
export const userLoginService=(registerData)=>{
    const params=new URLSearchParams()
    for(let key in registerData){
        params.append(key,registerData[key]);}
    
    return request.post('/user/login',params);
}
//获取用户详细信息
export const userInfoService = ()=>{
    return request.get('/user/getUserInfo')
}


//获取用户角色
export const userRoleService = ()=>{
    return request.get('/user/getUserRole')
}

//修改个人信息
export const userInfoUpdateService = (userInfoData)=>{
   return request.put('/user/updateUserInfo',userInfoData)
}

//修改头像
// export const userAvatarUpdateService = ()=>{
//     const params = new URLSearchParams();
//     // params.append('avatarUrl',avatarUrl)
//     return request.patch('/user/updateAvatar')
// }
export const userAvatarUpdateService = (imgUrl) => {
    const params = new URLSearchParams();
    params.append('imgUrl', imgUrl);  // 添加图片地址到请求参数

    return request.post('/user/updataAvatar', params)
}

//申请成为维修人员
export const submitRepairmanApplication = (repairmanApplication) => {
    return request.post('/user/apply', repairmanApplication)
}



//获取我发起的工单
export const getMyMaintainOrder = (params) => {
    return request.get('/deviceMaintain/getMyMaintainOrder', { params })
}
//获取我的维修工单
export const getMyRepairOrder = (params) => {
    return request.get('/deviceMaintain/getMyRepairOrder', { params })
}

//编辑我的维修工单
export const updateMyRepairOrder=(maintainRecord)=>{
    return request.put('/deviceMaintain/updateMyRepairOrder',maintainRecord)

}


// 添加设备到用户
export const addDeviceToUser = (params) => {
    return request.get('/deviceToUser/addDeviceToUser', { params });
};

// 从用户移除设备
export const removeDeviceFromUser = (params) => {
    return request.get('/deviceToUser/removeDeviceFromUser', { params });
};

// 根据用户ID获取设备
export const getDevicesByUserId = (params) => {
    return request.get('/deviceToUser/getDevicesByUserId', { params });
};
