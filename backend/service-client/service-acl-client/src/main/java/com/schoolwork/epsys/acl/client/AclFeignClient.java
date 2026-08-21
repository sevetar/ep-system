package com.schoolwork.epsys.acl.client;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

@FeignClient(value = "service-acl")
public interface AclFeignClient {
    //    @GetMapping("/api/product/inner/getSkuInfoVo/{skuId}")
    //    public SkuInfoVo getSkuInfoVo(@PathVariable Long skuId);

    @GetMapping("/admin/roleRequest")
    Boolean roleRequest(@RequestParam("userId") Integer userId,
                        @RequestParam("permissionId") Integer permissionId);

    @RequestMapping("/admin/getUsernameById")
    public String getUsernameById(@RequestParam Integer userId);

    @RequestMapping("/role/addUsertoRole3")
    public Boolean addUsertoRole3(@RequestParam("userId") Integer userId,@RequestParam("roleId") Integer roleId);

    @RequestMapping("/deviceToUser/isDeviceOwnedByUser")
    Boolean isDeviceOwnedByUser(@RequestParam("userId") Integer userId,
                                @RequestParam("deviceId") Integer deviceId);


}
