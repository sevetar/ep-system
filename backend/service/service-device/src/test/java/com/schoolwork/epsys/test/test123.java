package com.schoolwork.epsys.test;

import com.schoolwork.epsys.device.mapper.DeviceinstanceMapper;
import com.schoolwork.epsys.device.mapper.DevicemodelMapper;
import com.schoolwork.epsys.device.service.DeviceinstanceService;
import com.schoolwork.epsys.device.service.DevicemodelService;
import com.schoolwork.epsys.model.acl.Permissions;
import com.schoolwork.epsys.model.device.Deviceinstance;
import com.schoolwork.epsys.model.device.Devicemodel;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.web.bind.annotation.RequestParam;


import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import java.util.List;

@SpringBootTest
@ActiveProfiles("test")
public class test123 {

    @Autowired
    private DevicemodelService devicemodelService;

    @Autowired
    private DevicemodelMapper devicemodelMapper;

    @Autowired
    private DeviceinstanceService deviceinstanceService;

    @Autowired
    private DeviceinstanceMapper deviceinstanceMapper;

    @Test
    public void testInsert() {
        Integer pageNum = 1,pageSize = 10;
        Integer id = 1;
        Page<Deviceinstance> page = new Page<>(pageNum, pageSize);
        QueryWrapper<Deviceinstance> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("model_id", id);
        // 查询数据库并应用分页和条件
        List<Deviceinstance> list = deviceinstanceService.page(page, queryWrapper).getRecords();
        for (Deviceinstance deviceinstance : list) {
            System.out.println(deviceinstance);
        }

//        List<Deviceinstance>deviceinstanceList = deviceinstanceMapper.selectList(null);
//        for(Deviceinstance deviceinstance:deviceinstanceList){
//            System.out.println(deviceinstance);
//        }
    }

    @Test
    public void testPageQuery() {
        // 分页参数
        Integer pageNum = 1;
        Integer pageSize = 3;

        // 1. 使用 MyBatis-Plus 的 Page 类构造分页参数
        Page<Devicemodel> page = new Page<>(pageNum, pageSize);

        // 2. 可选：添加查询条件（按需使用）
        QueryWrapper<Devicemodel> queryWrapper = new QueryWrapper<>();
        // queryWrapper.like("name", "iPhone"); // 示例：模糊查询 name 包含 "iPhone" 的记录

        // 3. 执行分页查询（方式一：通过 Service 层）
        Page<Devicemodel> resultPage = devicemodelService.page(page, queryWrapper);

        // 或 方式二：直接通过 Mapper 层（需确保 DevicemodelMapper 继承 BaseMapper）
        // Page<Devicemodel> resultPage = devicemodelMapper.selectPage(page, queryWrapper);

        // 4. 打印分页结果
//        System.out.println("总记录数: " + resultPage.getTotal());
        System.out.println("当前页记录: " + resultPage.getRecords());
//        System.out.println("当前页码: " + resultPage.getCurrent());
//        System.out.println("每页大小: " + resultPage.getSize());
//        System.out.println("总页数: " + resultPage.getPages());
    }
}