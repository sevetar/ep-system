package com.schoolwork.epsys.acl.controller;


import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.schoolwork.epsys.acl.service.DevicetousersService;
import com.schoolwork.epsys.acl.saga.DeviceBindingSagaService;
import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.model.acl.Devicetousers;
import com.schoolwork.epsys.utils.WebUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 设备领用关系接口，负责用户与设备的绑定、解绑和关系查询。
 */
@RestController
@RequestMapping("/deviceToUser")
public class DeviceToUserController {


    @Autowired
    private DevicetousersService deviceToUserService;

    @Autowired
    private DeviceBindingSagaService deviceBindingSagaService;

    /** 提交设备领用 Saga，请求被受理不代表 Device 侧已完成。 */
    @RequestMapping("/addDeviceToUser")
    public void addDeviceToUser(HttpServletRequest req,HttpServletResponse resp,
                                   @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
                                   @RequestParam Integer userId,@RequestParam Integer deviceId) {
        String requestId = resolveRequestId(idempotencyKey);
        DeviceBindingSagaService.SagaRequestResult result =
                deviceBindingSagaService.requestBind(userId, deviceId, requestId);
        writeSagaResult(resp, result);
    }

    /** 提交设备解绑 Saga；失败结果会把 ACL 关系补偿回 ACTIVE。 */
    @RequestMapping("/removeDeviceFromUser")
    public void removeDeviceFromUser(HttpServletRequest req,HttpServletResponse resp,
                                        @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
                                        @RequestParam Integer userId,@RequestParam  Integer deviceId) {
        DeviceBindingSagaService.SagaRequestResult result = deviceBindingSagaService.requestUnbind(
                userId, deviceId, resolveRequestId(idempotencyKey));
        writeSagaResult(resp, result);
    }

    /**
     * 按用户 ID 分页查询其设备领用关系。
     */
    @RequestMapping("/getDevicesByUserId")
    public void getDevicesByUserId(HttpServletRequest req,HttpServletResponse resp,@RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                                   @RequestParam(value = "pageSize", defaultValue = "3") int pageSize,
                                               @RequestParam Integer userId) {
        QueryWrapper<Devicetousers>queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("user_id", userId);
        Page<Devicetousers> page = new Page<>(pageNum, pageSize);
        deviceToUserService.page(page, queryWrapper);
        List<Devicetousers> deviceToUsers = page.getRecords();
        Map<String,Object> data=new HashMap();
        data.put("items",deviceToUsers);
        data.put("total", page.getTotal());
        Result result= Result.ok(data);
        WebUtil.writeJson(resp, result);

    }

    /**
     * 判断指定设备是否已绑定到指定用户，供报修权属校验使用。
     */
    @RequestMapping("/isDeviceOwnedByUser")
    public Boolean isDeviceOwnedByUser(@RequestParam Integer userId, @RequestParam Integer deviceId) {
        return deviceBindingSagaService.isActiveOwner(userId, deviceId);
    }

    private String resolveRequestId(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return UUID.randomUUID().toString();
        }
        String requestId = idempotencyKey.trim();
        if (requestId.length() > 128) {
            throw new IllegalArgumentException("Idempotency-Key 不能超过128个字符");
        }
        return requestId;
    }

    private void writeSagaResult(HttpServletResponse resp,
                                 DeviceBindingSagaService.SagaRequestResult result) {
        Map<String, Object> data = new HashMap<>();
        data.put("flag", result.accepted());
        data.put("alreadyApplied", result.alreadyApplied());
        data.put("status", result.status());
        data.put("requestId", result.requestId());
        Result<Map<String, Object>> response = result.accepted()
                ? Result.ok(data).message(result.message())
                : Result.<Map<String, Object>>error(result.message());
        WebUtil.writeJson(resp, response);
    }

}
