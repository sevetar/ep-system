package com.schoolwork.epsys.acl.controller;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.schoolwork.epsys.acl.service.UsertoroleService;
import com.schoolwork.epsys.model.acl.Usertorole;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 角色管理接口，负责维护用户与角色之间的关联关系。
 */
@RestController
@RequestMapping("/role")
public class RoleController {

    @Autowired
    UsertoroleService usertoroleService;

    /**
     * 将指定用户加入指定角色，建立用户与角色的关联记录。
     */
    @RequestMapping("/addUsertoRole3")
    public Boolean addUsertoRole3(@RequestParam("userId") Integer userId,@RequestParam("roleId") Integer roleId) {
        long existing = usertoroleService.count(
                new QueryWrapper<Usertorole>()
                        .eq("user_id", userId)
                        .eq("role_id", roleId)
        );
        if (existing > 0) {
            return true;
        }

        Usertorole usertorole = new Usertorole();
        usertorole.setRoleId(roleId);
        usertorole.setUserId(userId);  // 使用传入的 userId
        return usertoroleService.save(usertorole);
    }


}
