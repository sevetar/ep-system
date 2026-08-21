package com.schoolwork.epsys.device.controller;


import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.device.service.DeviceinstanceService;
import com.schoolwork.epsys.device.service.DevicemodelService;
import com.schoolwork.epsys.device.service.MaintainRecordService;
import com.schoolwork.epsys.message.client.MessageFeignClient;
import com.schoolwork.epsys.model.device.Deviceinstance;
import com.schoolwork.epsys.model.search.DeviceInstanceDoc;
import com.schoolwork.epsys.utils.WebUtil;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static com.schoolwork.epsys.mq.constant.MqConst.DECREASE_DEVICE_INSTANCE_ROUTING_KEY;
import static com.schoolwork.epsys.mq.constant.MqConst.DEVICE_INSTANCE_EXCHANGE;
import static com.schoolwork.epsys.mq.constant.MqConst.INCREASE_DEVICE_INSTANCE_ROUTING_KEY;

/**
 * 设备实例管理接口，负责设备实例的查询、保存、更新、删除和状态流转。
 */
@RestController
@RequestMapping("/deviceInstance")
public class DeviceInstanceInfo {

    @Autowired
    private DeviceinstanceService deviceinstanceService;

    @Autowired
    private DevicemodelService devicemodelService;

    @Autowired
    private MaintainRecordService maintainRecordService;

    @Autowired
    private MessageFeignClient messageFeignClient;

    @Autowired
    private RabbitTemplate rabbitTemplate;

    /**
     * 根据设备 ID 更新设备实例状态，供设备领用与归还等业务调用。
     */
    @RequestMapping("/updateDeviceInstanceStatus")
    public void updateDeviceInstanceStatus(HttpServletRequest req, HttpServletResponse resp,
                                           @RequestParam(value = "deviceId") Integer id,
                                           @RequestParam(value = "status") String status) {
        System.out.println("id=" + id);
        System.out.println("status=" + status);
        Deviceinstance deviceinstance =deviceinstanceService.getOne(new QueryWrapper<Deviceinstance>().eq("id", id));
        deviceinstance.setStatus(status);
        boolean isUpdated = deviceinstanceService.updateById(deviceinstance);
        if (isUpdated) {
            Result result = Result.ok("设备状态更新成功");
            WebUtil.writeJson(resp, result);
        } else {
            Result result = Result.error("设备状态更新失败");
            WebUtil.writeJson(resp, result);
        }
    }



    /**
     * 根据一组设备实例 ID 批量查询设备详情，供搜索服务回填业务数据。
     */
    @RequestMapping("/getDeviceInstanceListById")
    public List<Deviceinstance> getDeviceInstanceListById(HttpServletRequest req, HttpServletResponse resp,
                                                          @RequestBody List<Integer> deviceInstanceIds) {
        if (deviceInstanceIds == null || deviceInstanceIds.isEmpty()) {
            return null;
        }
        List<Deviceinstance>deviceInstanceList = deviceinstanceService.listByIds(deviceInstanceIds);
        System.out.println("deviceInstanceList="+deviceInstanceList);
        return deviceInstanceList;
    }



    /**
     * 按设备型号 ID 分页查询对应的设备实例简要信息。
     */
    @RequestMapping("/getBriefInfoList")
    public void getBriefInfoList(HttpServletRequest req, HttpServletResponse resp,
                                   @RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                                   @RequestParam(value = "pageSize", defaultValue = "3") int pageSize,
                                 @RequestParam(value = "id", required = false) Integer id) {
        Page<Deviceinstance> page = new Page<>(pageNum, pageSize);
        QueryWrapper<Deviceinstance> queryWrapper = new QueryWrapper<>();
        if (id != null) {
            queryWrapper.eq("model_id", id);
        }
        // 查询数据库并应用分页和条件
        List<Deviceinstance> list = deviceinstanceService.page(page, queryWrapper).getRecords();
        // 封装分页数据
        Map<String, Object> data = new HashMap<>();
        data.put("total", page.getTotal());
        data.put("items", list);
        // 返回结果
        Result result = Result.ok(data);
        WebUtil.writeJson(resp, result);
    }

    /**
     * 根据设备实例 ID 查询单台设备的完整详情。
     */
    @RequestMapping("/getTrueDetailInfoList/{id}")  // 使用 {id} 占位符
    public void getDetailInfoList(HttpServletRequest req, HttpServletResponse resp,
            @PathVariable Integer id  // 使用 @PathVariable 接收路径参数
    ) {
        QueryWrapper<Deviceinstance> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("id", id);
        Deviceinstance deviceinstance = deviceinstanceService.getOne(queryWrapper);

        Map<String, Object> data = new HashMap<>();
        data.put("deviceinstance", deviceinstance);
        Result result = Result.ok(data);
        WebUtil.writeJson(resp, result);
    }

    /**
     * 删除指定设备实例，并通过 RabbitMQ 通知下游服务同步删除相关数据。
     */
    @RequestMapping("/deviceTrueDeleteService/{id}")
    public void deviceTrueDeleteService(HttpServletRequest req, HttpServletResponse resp, @PathVariable Integer id) {
    System.out.println("这是删除的参数" + id);
    boolean isDeleted = deviceinstanceService.removeById(id);
    Integer maintainRecordId= id;
    if (isDeleted) {
        // 发送设备删除消息到 RabbitMQ
        rabbitTemplate.convertAndSend(
                DEVICE_INSTANCE_EXCHANGE,
                DECREASE_DEVICE_INSTANCE_ROUTING_KEY,
                maintainRecordId                          // 删除时只发 id 即可
        );

        Result result = Result.ok("设备删除成功");
        WebUtil.writeJson(resp, result);
    } else {
        Result result = Result.error("设备删除失败");
        WebUtil.writeJson(resp, result);
    }
    }

    /**
     * 新增或更新设备实例，并通过 RabbitMQ 同步设备搜索索引。
     */
    @RequestMapping("/updateDeviceInstance")
    public void updateDeviceInstance(HttpServletRequest req, HttpServletResponse resp, @RequestBody Deviceinstance deviceinstance) {
        if (deviceinstance == null) {
            WebUtil.writeJson(resp, Result.error("设备信息不能为空"));
            return;
        }

        Integer id = deviceinstance.getId();
        Deviceinstance existing = null;
        if (id != null) {
            existing = deviceinstanceService.getById(id);
            if (existing == null) {
                WebUtil.writeJson(resp, Result.error("设备实例不存在"));
                return;
            }
            mergeMissingFields(deviceinstance, existing);
        }

        if (deviceinstance.getModelId() == null) {
            WebUtil.writeJson(resp, Result.error("请选择设备型号"));
            return;
        }
        if (devicemodelService.getById(deviceinstance.getModelId()) == null) {
            WebUtil.writeJson(resp, Result.error("所选设备型号不存在"));
            return;
        }
        if (deviceinstance.getSerialNumber() == null || deviceinstance.getSerialNumber().trim().isEmpty()) {
            WebUtil.writeJson(resp, Result.error("设备序列号不能为空"));
            return;
        }

        if (id == null) {
            deviceinstance.setCreateAt(new Date());
            deviceinstance.setStatus("闲置");
            boolean isCreated = deviceinstanceService.save(deviceinstance);
            if (isCreated) {
                rabbitTemplate.convertAndSend(
                        DEVICE_INSTANCE_EXCHANGE,
                        INCREASE_DEVICE_INSTANCE_ROUTING_KEY,
                        toSearchDocument(deviceinstance)
                );
                Result result = Result.ok("设备信息添加成功");
                WebUtil.writeJson(resp, result);
                return;
            } else {
                Result result = Result.error("设备信息添加失败");
                WebUtil.writeJson(resp, result);
                return;
            }
        }
        // 更新逻辑
        boolean isUpdated = deviceinstanceService.updateById(deviceinstance);
        if (isUpdated) {
            rabbitTemplate.convertAndSend(
                    DEVICE_INSTANCE_EXCHANGE,
                    INCREASE_DEVICE_INSTANCE_ROUTING_KEY,
                    toSearchDocument(deviceinstance)
            );

            Result result = Result.ok("设备信息更新成功");
            WebUtil.writeJson(resp, result);
        } else {
            Result result = Result.error("设备信息更新失败");
            WebUtil.writeJson(resp, result);
        }
    }

    private void mergeMissingFields(Deviceinstance target, Deviceinstance source) {
        if (target.getModelId() == null) {
            target.setModelId(source.getModelId());
        }
        if (target.getSerialNumber() == null) {
            target.setSerialNumber(source.getSerialNumber());
        }
        if (target.getStatus() == null) {
            target.setStatus(source.getStatus());
        }
        if (target.getCreateAt() == null) {
            target.setCreateAt(source.getCreateAt());
        }
        if (target.getLocation() == null) {
            target.setLocation(source.getLocation());
        }
    }

    private DeviceInstanceDoc toSearchDocument(Deviceinstance deviceinstance) {
        DeviceInstanceDoc document = new DeviceInstanceDoc();
        document.setId(deviceinstance.getId());
        document.setModelId(deviceinstance.getModelId());
        document.setSerialNumber(deviceinstance.getSerialNumber());
        document.setStatus(deviceinstance.getStatus() == null ? null : deviceinstance.getStatus().toString());
        document.setCreateAt(deviceinstance.getCreateAt());
        document.setLocation(deviceinstance.getLocation());
        return document;
    }





}
