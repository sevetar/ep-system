package com.schoolwork.epsys.acl.controller;


import com.schoolwork.epsys.acl.mapper.PermissionsMapper;
import com.schoolwork.epsys.acl.service.PermissionsService;
import com.schoolwork.epsys.acl.service.UserService;
import com.schoolwork.epsys.model.acl.User;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;


/**
 * 管理端用户辅助接口，提供权限校验和用户信息查询能力。
 */
@RestController
@RequestMapping("/admin")
public class AdminController {

    @Autowired
    PermissionsMapper permissionsMapper;

    @Autowired
    UserService userService;

    /**
     * 校验指定用户是否拥有指定权限，供其他服务进行远程鉴权。
     */
    @RequestMapping("/roleRequest")
    public Boolean roleRequest(@RequestParam Integer userId,          // 从 ?userId=xxx 获取
                            @RequestParam Integer permissionId) {
        return permissionsMapper.hasPermission(userId, permissionId);
    }

    /**
     * 根据用户 ID 查询用户名，供通知等跨服务场景使用。
     */
    @RequestMapping("/getUsernameById")
    public String getUsernameById(@RequestParam Integer userId) {
        User user =userService.getById(userId);
        return user.getUsername();
    }
}
