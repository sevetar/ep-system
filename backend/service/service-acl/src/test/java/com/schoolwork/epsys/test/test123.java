package com.schoolwork.epsys.test;

import com.schoolwork.epsys.acl.mapper.PermissionsMapper;
import com.schoolwork.epsys.acl.service.impl.UserServiceImpl;
import com.schoolwork.epsys.model.acl.Permissions;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

@SpringBootTest
@ActiveProfiles("test")
//@Transactional  // 测试后自动回滚
//@Rollback        // 确保数据不污染数据库
public class test123 {
    @Autowired
    private PermissionsMapper mapper;
    @Autowired
    UserServiceImpl userService;
    @Autowired
    PermissionsMapper permissionsMapper;
    @Test
    void testSelect2() {


    }
    // 测试特定权限ID
    @Test
    void testSpecificPermission() {
        boolean result = permissionsMapper.hasPermission(3, 1);  // 检查用户1是否有权限2
        System.out.println("用户1是否有权限2: " + result);
    }

    @Test
    void testSelect() {
        System.out.println("okokok");
        Permissions p = new Permissions();
        p.setPermissionName("test");
        System.out.println(p.getPermissionName());


    }
}
//    @Test
//    void testInsert() {
//        Permissions p = new Permissions();
//        p.setPermissionName("test");
//        mapper.insert(p);
//        assertNotNull(p.getId());
//    }
