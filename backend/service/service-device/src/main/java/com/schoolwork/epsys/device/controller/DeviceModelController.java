package com.schoolwork.epsys.device.controller;


import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.device.mapper.DevicemodelMapper;
import com.schoolwork.epsys.device.service.DevicemodelService;
import com.schoolwork.epsys.utils.WebUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.schoolwork.epsys.model.device.Devicemodel;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 设备型号管理接口，负责型号的分页查询、新增、修改和删除。
 */
@RestController
@RequestMapping("/deviceModel")
public class DeviceModelController {

    @Autowired
    private DevicemodelService devicemodelService;

    @Autowired
    DevicemodelMapper devicemodelMapper;
//    Page<User> page = new Page<>(1, 5);
//    userMapper.selectPage(page, null);
//    //获取分页数据
//    List<User> list = page.getRecords();

    /**
     * 分页查询设备型号，可按设备分类 ID 进行筛选。
     */
    @RequestMapping("/getInfoList")
    public void getInfoList(HttpServletRequest req, HttpServletResponse resp,
                            @RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                            @RequestParam(value = "pageSize", defaultValue = "3") int pageSize,
                            @RequestParam(value = "categoryId", required = false) Integer categoryId) {
        System.out.println("这是categoryId="+categoryId);

        // 创建查询条件
        QueryWrapper<Devicemodel> queryWrapper = new QueryWrapper<>();
        if (categoryId != null) {
            queryWrapper.eq("category_id", categoryId);
        }

        // 创建分页对象
        Page<Devicemodel> page = new Page<>(pageNum, pageSize);

        // 查询数据库并应用分页和条件
//        Page<Devicemodel> resultPage = devicemodelService.page(page, queryWrapper);
        devicemodelMapper.selectPage(page, queryWrapper);
        List<Devicemodel> list = page.getRecords();

        System.out.println("list="+list);


        // 封装分页数据
        Map<String, Object> data = new HashMap<>();
        data.put("total", page.getTotal());
        data.put("items", list);

        // 返回结果
        Result result = Result.ok(data);
        WebUtil.writeJson(resp, result);
    }

    /**
     * 保存设备型号；请求体包含 ID 时执行更新，否则执行新增。
     */
    @RequestMapping("/addDeviceModel")
    public  void addDeviceModel(HttpServletRequest req, HttpServletResponse resp,
                            @RequestBody Devicemodel devicemodel) {
        Integer id= devicemodel.getId();
        if(id == null) {
            // 设置创建时间
            devicemodel.setCreateAt(new java.util.Date());
            // 保存设备模型信息
            boolean success = devicemodelService.save(devicemodel);
            if (success) {
                Result result = Result.ok("设备模型添加成功");
                WebUtil.writeJson(resp, result);
            } else {
                Result result = Result.error("设备模型添加失败");
                WebUtil.writeJson(resp, result);
            }
            return;
        }else{
            devicemodel.setCreateAt(new java.util.Date());
            boolean success=devicemodelService.updateById(devicemodel);
            if(success){
                Result result = Result.ok("设备模型更新成功");
                WebUtil.writeJson(resp, result);
            }else{
                Result result = Result.error("设备模型更新失败");
                WebUtil.writeJson(resp, result);
            }
            return;
        }
    }

    /**
     * 根据型号 ID 删除设备型号。
     */
    @RequestMapping("/deleteDeviceModel")
    public void deleteDeviceModel(HttpServletRequest req, HttpServletResponse resp,
                            @RequestParam(value = "id") Integer id) {
        Boolean success = devicemodelService.removeById(id);
        if (success) {
            Result result = Result.ok("设备模型删除成功");
            WebUtil.writeJson(resp, result);
        } else {
            Result result = Result.error("设备模型删除失败");
            WebUtil.writeJson(resp, result);
        }
    }



}
