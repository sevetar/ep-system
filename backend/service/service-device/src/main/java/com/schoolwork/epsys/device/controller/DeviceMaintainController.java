package com.schoolwork.epsys.device.controller;


import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.schoolwork.epsys.acl.client.AclFeignClient;
import com.schoolwork.epsys.common.Result;
import com.schoolwork.epsys.device.mapper.MaintainRecordMapper;
import com.schoolwork.epsys.device.dispatch.trigger.DispatchTriggerService;
import com.schoolwork.epsys.device.dispatch.trigger.DispatchTriggerType;
import com.schoolwork.epsys.device.knowledge.WorkOrderCompletionService;
import com.schoolwork.epsys.device.service.ClaimOrderConflictException;
import com.schoolwork.epsys.device.service.ClaimOrderResult;
import com.schoolwork.epsys.device.service.MaintainRecordService;
import com.schoolwork.epsys.message.client.MessageFeignClient;
import com.schoolwork.epsys.model.device.Devicemodel;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.model.shared.UserNotification;
import com.schoolwork.epsys.utils.WebUtil;
import com.schoolwork.epsys.utils.JwtUtils;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 设备维护工单接口，负责报修、审批、抢单、进度查询和维修完成处理。
 */
@RestController
@RequestMapping("/deviceMaintain")
public class DeviceMaintainController {

    @Autowired
    private MaintainRecordService maintainRecordService;

    @Autowired
    private MaintainRecordMapper maintainRecordMapper;

    @Autowired
    MessageFeignClient messageFeignClient;

    @Autowired
    private RabbitTemplate rabbitTemplate;

    @Autowired
    private AclFeignClient aclFeignClient;

    @Autowired
    private RedissonClient redissonClient;

    @Autowired
    private DispatchTriggerService dispatchTriggerService;

    @Autowired
    private WorkOrderCompletionService workOrderCompletionService;

    @Value("${dispatch.auto.manual-permission-id:1001}")
    private int manualDispatchPermissionId;




    /**
     * 维修人员抢领维护工单，通过 Redisson、幂等键、唯一领取记录和乐观锁避免重复抢单。
     */
    @PostMapping("/getMaintainOrder")
    public void getMaintainOrder(HttpServletRequest req, HttpServletResponse resp,
                                 @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
                                 @RequestBody MaintainRecord maintainRecord) {
        if (maintainRecord == null || maintainRecord.getId() == null || maintainRecord.getMiantainId() == null) {
            WebUtil.writeJson(resp, Result.error("工单 ID 和维修人员 ID 不能为空！"));
            return;
        }



        String requestId = resolveIdempotencyKey(
                idempotencyKey, maintainRecord.getId(), maintainRecord.getMiantainId());
        if (requestId.length() > 64) {
            WebUtil.writeJson(resp, Result.error("Idempotency-Key 长度不能超过 64 个字符！"));
            return;
        }

        // 同一工单在所有服务实例中使用相同的锁 key。
        String lockKey = "order:lock:" + maintainRecord.getId();
        RLock lock = redissonClient.getLock(lockKey);

        boolean isLocked = false;
        Result result = Result.error("抢单失败，请稍后重试！");

        try {
            // 抢单请求直接竞争锁，不排队等待；未指定 leaseTime 时由 Redisson watchdog 自动续期。
            isLocked = lock.tryLock();

            if (isLocked) {
                ClaimOrderResult claimResult = maintainRecordService.claimOrder(
                        maintainRecord.getId(), maintainRecord.getMiantainId(), requestId);
                result = buildClaimResult(claimResult);
            } else {
                result = Result.error("该工单正在被其他维修人员处理，请刷新后重试！");
            }

        } catch (DuplicateKeyException e) {
            result = Result.error("工单已被领取或幂等键已被使用，请刷新后重试！");
        } catch (Exception e) {
            e.printStackTrace();
            result = Result.error("系统异常：" + e.getMessage());
        } finally {
            if (isLocked && lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
            WebUtil.writeJson(resp, result);
        }
    }

    private String resolveIdempotencyKey(String idempotencyKey, Integer orderId, Integer repairmanId) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            return "claim:" + orderId + ":" + repairmanId;
        }
        return idempotencyKey.trim();
    }

    private Result buildClaimResult(ClaimOrderResult claimResult) {
        return switch (claimResult) {
            case SUCCESS -> Result.ok("获取订单成功！");
            case IDEMPOTENT_SUCCESS -> Result.ok("获取订单成功！");
            case ORDER_NOT_FOUND -> Result.error("未找到对应的工单！");
            case ORDER_NOT_CLAIMABLE -> Result.error("工单当前状态不可领取！");
            case ORDER_ALREADY_CLAIMED -> Result.error("工单已被其他维修人员领取，请刷新后重试！");
            case IDEMPOTENCY_KEY_CONFLICT -> Result.error("Idempotency-Key 已被其他抢单请求使用！");
        };
    }




    /**
     * 分页查询全部设备维护工单，供管理端查看和审批。
     */
    @RequestMapping("/getMaintainRecord")
    public  void getMaintainRecord(HttpServletRequest req, HttpServletResponse resp,
                                   @RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                                   @RequestParam(value = "pageSize", defaultValue = "3") int pageSize,
                                   @RequestParam(value = "keyword", required = false) String keyword,
                                   @RequestParam(value = "status", required = false) String status) {
        Page<MaintainRecord> page = new Page<>(pageNum, pageSize);
        QueryWrapper<MaintainRecord> queryWrapper = new QueryWrapper<>();
        if (status != null && !status.isBlank()) {
            queryWrapper.eq("status", status.trim());
        }
        if (keyword != null && !keyword.isBlank()) {
            String trimmedKeyword = keyword.trim();
            queryWrapper.and(wrapper -> {
                wrapper.like("description", trimmedKeyword)
                        .or().like("repair_process", trimmedKeyword)
                        .or().like("solution", trimmedKeyword);
                try {
                    int numericKeyword = Integer.parseInt(trimmedKeyword);
                    wrapper.or().eq("id", numericKeyword).or().eq("device_id", numericKeyword);
                } catch (NumberFormatException ignored) {
                    // 非数字关键词只搜索文本字段。
                }
            });
        }
        queryWrapper.orderByDesc("start_time");
        maintainRecordMapper.selectPage(page, queryWrapper);
        List<MaintainRecord> records = page.getRecords();

        Map data = new HashMap();
        data.put("records", records);
        data.put("total", page.getTotal());
        Result result =Result.ok(data);
        WebUtil.writeJson(resp, result);

    }

    /**
     * 接单平台只返回审批通过且尚未被领取的工单。
     */
    @RequestMapping("/getClaimableMaintainRecords")
    public void getClaimableMaintainRecords(HttpServletResponse resp,
                                            @RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                                            @RequestParam(value = "pageSize", defaultValue = "5") int pageSize) {
        Page<MaintainRecord> page = new Page<>(pageNum, pageSize);
        QueryWrapper<MaintainRecord> queryWrapper = new QueryWrapper<>();
        queryWrapper.in("status", "已通过", "待领取")
                .isNull("miantain_id")
                .orderByAsc("start_time");
        maintainRecordMapper.selectPage(page, queryWrapper);
        Map<String, Object> data = new HashMap<>();
        data.put("records", page.getRecords());
        data.put("total", page.getTotal());
        WebUtil.writeJson(resp, Result.ok(data));
    }

    /**
     * 审批中心只返回待审批和已经做出审批结果的记录。
     */
    @RequestMapping("/getApprovalRecords")
    public void getApprovalRecords(HttpServletResponse resp,
                                   @RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                                   @RequestParam(value = "pageSize", defaultValue = "5") int pageSize,
                                   @RequestParam(value = "approvalStatus", required = false) String approvalStatus) {
        Page<MaintainRecord> page = new Page<>(pageNum, pageSize);
        QueryWrapper<MaintainRecord> queryWrapper = new QueryWrapper<>();
        if ("待审批".equals(approvalStatus)) {
            queryWrapper.eq("status", "待审批").isNull("approval_time");
        } else if ("已审批".equals(approvalStatus)) {
            queryWrapper.isNotNull("approval_time");
        } else {
            queryWrapper.and(wrapper -> wrapper.eq("status", "待审批").or().isNotNull("approval_time"));
        }
        queryWrapper.orderByAsc("approval_time").orderByDesc("start_time");
        maintainRecordMapper.selectPage(page, queryWrapper);
        Map<String, Object> data = new HashMap<>();
        data.put("records", page.getRecords());
        data.put("total", page.getTotal());
        WebUtil.writeJson(resp, Result.ok(data));
    }


    /**
     * 根据工单 ID 查询单条维护记录详情。
     */
    @RequestMapping("/getMaintainRecordById")
    public  void getMaintainRecordById(HttpServletRequest req, HttpServletResponse resp,
                                   @RequestParam(value = "id") int id) {
        MaintainRecord maintainRecord = maintainRecordMapper.selectById(id);
        Map data = new HashMap();
        data.put("record", maintainRecord);
        Result result =Result.ok(data);
        WebUtil.writeJson(resp, result);
    }

    /**
     * 创建维护工单，并在创建成功后通知在线审批人员刷新待办列表。
     */
    @RequestMapping("/createMaintainRecord")
    public void createMaintainRecord(HttpServletRequest req, HttpServletResponse resp,
                                     @RequestBody MaintainRecord maintainRecord) {
        if (maintainRecord == null || maintainRecord.getDeviceId() == null || maintainRecord.getOperatorId() == null) {
            WebUtil.writeJson(resp, Result.error("设备 ID 和报修人 ID 不能为空"));
            return;
        }
        if (!Boolean.TRUE.equals(aclFeignClient.isDeviceOwnedByUser(
                maintainRecord.getOperatorId(), maintainRecord.getDeviceId()))) {
            WebUtil.writeJson(resp, Result.error("只能为当前用户已领用的设备发起报修"));
            return;
        }
        if (maintainRecord.getMaintenanceType() == null || maintainRecord.getDescription() == null
                || maintainRecord.getDescription().trim().isEmpty()) {
            WebUtil.writeJson(resp, Result.error("请完整填写问题类型和问题描述"));
            return;
        }

        maintainRecord.setStartTime(new Date());
        maintainRecord.setStatus("待审批");

        // 保存维护记录
        boolean isCreated = maintainRecordService.save(maintainRecord);

        if (isCreated) {
            // 发送广播通知管理员
            try {
                System.out.println("发送广播通知管理员");
                messageFeignClient.sendToTopic4Maintain();  // Feign调用
                Result result = Result.ok("维护记录创建成功，消息已广播");
                WebUtil.writeJson(resp, result);
            } catch (Exception e) {
                e.printStackTrace();
                Result result = Result.ok("维护记录创建成功，但消息广播失败");
                WebUtil.writeJson(resp, result);
            }
        } else {
            Result result = Result.error("维护记录创建失败");
            WebUtil.writeJson(resp, result);
        }
    }

    /**
     * 审批维护工单，通知申请人审批结果，并在通过时通知维修人员刷新工单。
     */
    @RequestMapping("/approvalMaintainRecord")
    public void approvalMaintainRecord(HttpServletRequest req, HttpServletResponse resp,
                                   @RequestBody MaintainRecord maintainRecord) {
    if (maintainRecord == null || maintainRecord.getId() == null || maintainRecord.getApprovalId() == null
            || !("已通过".equals(maintainRecord.getStatus()) || "已拒绝".equals(maintainRecord.getStatus()))) {
        WebUtil.writeJson(resp, Result.error("工单 ID、审批人和有效审批结果不能为空"));
        return;
    }
    MaintainRecord existing = maintainRecordService.getById(maintainRecord.getId());
    if (existing == null || existing.getApprovalTime() != null || !"待审批".equals(existing.getStatus())) {
        WebUtil.writeJson(resp, Result.error("该工单已审批或当前状态不可审批"));
        return;
    }
    boolean approved = "已通过".equals(maintainRecord.getStatus());
    DispatchTriggerService.ApprovalResult approvalResult = dispatchTriggerService.approve(
            existing, maintainRecord.getApprovalId(), approved);
    Boolean isUpdated = approvalResult.updated();
    UserNotification userNotification = new UserNotification();
    String uname=aclFeignClient.getUsernameById(existing.getOperatorId());
    userNotification.setUsername(uname);
    userNotification.setNotification("您的报修单"+existing.getId()+"已被审批，审批结果为："
            +(approved ? "已通过，等待维修人员领取" : "已拒绝"));
    userNotification.setReceiverId(existing.getOperatorId());
    userNotification.setIsRead(0);
    userNotification.setCreateTime(new Date());
    if (isUpdated) {
        // 1. 通知单个用户（审批结果）
        rabbitTemplate.convertAndSend(
                "approval.direct",   // 交换机
                "user.notify",       // routingKey
                userNotification       // 通知用户
        );
        System.out.println("这里开始准备发送消息给维修员");
       if(approved){
           System.out.println("这里开始发送消息给维修员");
           // 2. 通知所有维修员刷新
           rabbitTemplate.convertAndSend(
                   "approval.direct",
                   "repairman.refresh",
                   existing
           );
       }
        String message = approvalResult.urgentTriggered()
                ? "审批成功，紧急工单已进入自动派单队列！"
                : "审批成功，工单已进入抢单池！";
        Result result = Result.ok(message);
        WebUtil.writeJson(resp, result);
    } else {
        Result result = Result.error("审批失败，可能已被他人审批，请刷新后重试！");
        WebUtil.writeJson(resp, result);
        }
    }

    /**
     * 管理员手动触发自动派单。身份来自可信 JWT，权限仍由 ACL 服务判定。
     */
    @PostMapping("/{orderId}/auto-dispatch")
    public void triggerAutoDispatch(HttpServletResponse resp,
                                    @PathVariable Integer orderId,
                                    @RequestHeader(value = "Authorization", required = false) String authorization,
                                    @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey) {
        Integer userId = authenticatedUserId(authorization);
        if (userId == null) {
            WebUtil.writeJson(resp, Result.error("请先登录后再触发自动派单"));
            return;
        }
        if (!Boolean.TRUE.equals(aclFeignClient.roleRequest(userId, manualDispatchPermissionId))) {
            WebUtil.writeJson(resp, Result.error("当前用户没有自动派单权限"));
            return;
        }
        if (idempotencyKey == null || idempotencyKey.isBlank() || idempotencyKey.length() > 128) {
            WebUtil.writeJson(resp, Result.error("Idempotency-Key 必填且不能超过 128 个字符"));
            return;
        }
        DispatchTriggerService.TriggerReceipt receipt = dispatchTriggerService.trigger(
                orderId, DispatchTriggerType.MANUAL, "admin:" + userId + ":" + idempotencyKey.trim());
        WebUtil.writeJson(resp, receipt != null
                ? Result.ok(Map.of(
                        "message", "自动派单事件已受理",
                        "event_id", receipt.eventId(),
                        "dispatch_id", receipt.dispatchId(),
                        "thread_id", receipt.threadId()))
                : Result.error("工单不存在、已被领取或当前状态不可派单"));
    }

    private Integer authenticatedUserId(String authorization) {
        if (authorization == null || authorization.isBlank()) {
            return null;
        }
        try {
            Claims claims = JwtUtils.parseJwt(authorization.trim());
            return Integer.valueOf(String.valueOf(claims.get("id")));
        } catch (Exception ignored) {
            return null;
        }
    }


    /**
     * 按发起人 ID 分页查询当前用户提交的维护工单。
     */
    @RequestMapping("/getMyMaintainOrder")
    public void getMyMaintainOrder(HttpServletRequest req, HttpServletResponse resp,
                                   @RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                                   @RequestParam(value = "pageSize", defaultValue = "3") int pageSize,@RequestParam(value = "userId") String userId) {

        // 创建分页对象
        Page<MaintainRecord> page = new Page<>(pageNum, pageSize);
        QueryWrapper<MaintainRecord> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("operator_id", userId);
        maintainRecordMapper.selectPage(page, queryWrapper);
        List<MaintainRecord> records = page.getRecords();
        Map data = new HashMap();
        data.put("records", records);
        data.put("total", page.getTotal());
        Result result =Result.ok(data);
        WebUtil.writeJson(resp, result);

    }

    /**
     * 按维修人员 ID 分页查询其已领取的维修工单。
     */
    @RequestMapping("/getMyRepairOrder")
    public void getMyRepairOrder(HttpServletRequest req, HttpServletResponse resp,
                                   @RequestParam(value = "pageNum", defaultValue = "1") int pageNum,
                                   @RequestParam(value = "pageSize", defaultValue = "3") int pageSize,@RequestParam(value = "userId") String userId) {

        // 创建分页对象
        Page<MaintainRecord> page = new Page<>(pageNum, pageSize);
        QueryWrapper<MaintainRecord> queryWrapper = new QueryWrapper<>();
        queryWrapper.eq("miantain_id", userId);
        maintainRecordMapper.selectPage(page, queryWrapper);
        List<MaintainRecord> records = page.getRecords();
        Map data = new HashMap();
        data.put("records", records);
        data.put("total", page.getTotal());
        Result result =Result.ok(data);
        WebUtil.writeJson(resp, result);
    }

    /**
     * 将维修工单标记为完成，并在同一事务写入知识事件 Outbox。
     */
    @RequestMapping("/updateMyRepairOrder")
    public void updateMyRepairOrder(HttpServletRequest req, HttpServletResponse resp,
                                   @RequestBody MaintainRecord maintainRecord) {
        WorkOrderCompletionService.CompletionResult completion = workOrderCompletionService.complete(
                maintainRecord == null ? null : maintainRecord.getId(),
                maintainRecord == null ? null : maintainRecord.getRepairProcess(),
                maintainRecord == null ? null : maintainRecord.getSolution(),
                maintainRecord == null ? null : maintainRecord.getRootCause(),
                maintainRecord == null ? null : maintainRecord.getVerificationResult(),
                maintainRecord == null ? null : maintainRecord.getReplacedParts(),
                maintainRecord == null ? null : maintainRecord.getKnowledgeTags());
        WebUtil.writeJson(resp, completion.completed()
                ? Result.ok(Map.of("message", completion.message(), "knowledgeEventId", completion.eventId()))
                : Result.error(completion.message()));
    }

    /** 查询 RabbitMQ 发布状态和 Agent 最终知识摄取状态。 */
    @GetMapping("/knowledgeIngestionStatus")
    public void knowledgeIngestionStatus(HttpServletResponse resp,
                                         @RequestParam("eventId") String eventId) {
        WorkOrderCompletionService.KnowledgeStatusResult result =
                workOrderCompletionService.getKnowledgeStatus(eventId);
        WebUtil.writeJson(resp, result == null
                ? Result.error("未找到对应的知识事件")
                : Result.ok(result));
    }
//    List<Integer> maintainRecordIds =null;



}
