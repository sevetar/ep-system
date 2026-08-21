package com.schoolwork.epsys.device.controller;


import com.schoolwork.epsys.acl.client.AclFeignClient;
import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.common.ResultCodeEnum;
import com.schoolwork.epsys.device.service.DevicecategoryService;
import com.schoolwork.epsys.model.device.Devicecategory;
import com.schoolwork.epsys.utils.JwtUtils;
import com.schoolwork.epsys.utils.WebUtil;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 设备分类管理接口，负责分类列表查询以及分类的新增、删除和修改。
 */
@RestController
@RequestMapping("/device")
public class DeviceCategoryController {


    @Autowired
    DevicecategoryService devicecategoryService;

    @Autowired
    AclFeignClient aclFeignClient;

    /**
     * 校验登录令牌后查询全部设备分类。
     */
    @RequestMapping("/category/list")
    public void getListInfo(@RequestHeader(value = "Authorization", required = false) String authorization,
                            HttpServletRequest req, HttpServletResponse resp){

        String token = authorization;
        System.out.println("这是token   "+token);
        if(token == null || token.isEmpty()){
            Result result = Result.build(null, ResultCodeEnum.USERNAEM_ERROR);
            WebUtil.writeJson(resp,result);
            return;
        }
        Claims claims = JwtUtils.parseJwt(token);
        Integer id = claims.get("id", Integer.class);
        String username = claims.get("username", String.class);

        List<Devicecategory> devicecategories= devicecategoryService.list();
        Map data =new HashMap();
        data.put("categories",devicecategories);
        Result result = Result.ok(data);
        // 将Result对象转换为json响应给客户端
        WebUtil.writeJson(resp,result);

    }

    /**
     * 新增设备分类，并记录分类的创建时间。
     */
    @RequestMapping("/category/add")
    public void addInfo(@RequestHeader(value = "Authorization", required = false) String authorization,
                       @RequestBody Devicecategory devicecategory,
                       HttpServletResponse resp){
        String token = authorization;
        Claims claims = JwtUtils.parseJwt(token);
        Integer id = claims.get("id", Integer.class);
        // 设置创建人和时间
        devicecategory.setCreateAt(new Date());
        // 保存分类信息
        boolean flag=devicecategoryService.save(devicecategory);

        if(flag){
            Result result = Result.ok(null);
            WebUtil.writeJson(resp, result);
            return;
        }
        Result result = Result.build(null, ResultCodeEnum.LAZY_ERROR);
        WebUtil.writeJson(resp, result);
    }

    /**
     * 根据分类 ID 删除设备分类。
     */
    @RequestMapping("/category/delete")
    public void deleteInfo(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("id") Integer id,
            HttpServletResponse resp){
        String token = authorization;
        Claims claims = JwtUtils.parseJwt(token);
        Integer userId = claims.get("id", Integer.class);
        // 检查该用户是否有权限删除该分类
        //..懒得写，之后写


        // 删除分类
        boolean isDeleted = devicecategoryService.removeById(id);
        if(isDeleted){
            Result result = Result.ok("删除成功");
            WebUtil.writeJson(resp, result);
        }else{
            Result result = Result.error("删除失败");
            WebUtil.writeJson(resp, result);
        }
    }

    /**
     * 校验登录令牌和分类是否存在后，更新设备分类信息。
     */
    @RequestMapping("/category/update")
    public void updateInfo(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody Devicecategory devicecategory,
            HttpServletResponse resp) {
        System.out.println("接收到的 Token: " + authorization);
        if (authorization == null || authorization.isEmpty()) {
            Result result = Result.error("Token 无效");
            WebUtil.writeJson(resp, result);
            return;
        }

        try {
            Claims claims = JwtUtils.parseJwt(authorization);
            Integer id = claims.get("id", Integer.class);
            System.out.println("用户 ID: " + id);

            System.out.println("这是更新的分类信息: " + devicecategory.toString());

            devicecategory.setCreateAt(new Date());
            Devicecategory category = devicecategoryService.getById(devicecategory.getId());
            if (category == null) {
                Result result = Result.error("分类信息不存在");
                WebUtil.writeJson(resp, result);
                return;
            }

            boolean success = devicecategoryService.updateById(devicecategory);
            if (success) {
                Result result = Result.ok(null);
                WebUtil.writeJson(resp, result);
            } else {
                Result result = Result.error("更新失败，请检查输入的分类信息！");
                WebUtil.writeJson(resp, result);
            }
        } catch (Exception e) {
            e.printStackTrace();
            Result result = Result.error("系统异常");
            WebUtil.writeJson(resp, result);
        }
    }





}
