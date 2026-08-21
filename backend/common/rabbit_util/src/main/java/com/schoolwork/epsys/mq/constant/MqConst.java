package com.schoolwork.epsys.mq.constant;

public class MqConst {
    /**
     * 消息补偿
     */

    public static final String REPAIR_EXCHANGE = "repair_exchange";
    public static final String REPAIR_APPLY_QUEUE = "repair_apply_queue"; // 申请成为维修人员


    public static final String APPROVAL_DIRECT_EXCHANGE = "approval.direct"; // 新增交换机
    public static final String USER_NOTIFY_QUEUE = "user_notify_queue";      // 新增队列
    public static final String USER_NOTIFY_ROUTING_KEY = "user.notify";       // 新增路由键
    public static final String REPAIRMAN_REFRESH_ROUTING_KEY = "repairman.refresh"; // 维修人员用
    public static final String REPAIR_MAN_REFRESH_QUEUE = "repairman_refresh_queue"; // 通知维修人员刷新


    public static final String DEVICE_INSTANCE_EXCHANGE = "device_instance_exchange";
    public static final String INCREASE_DEVICE_INSTANCE_ROUTING_KEY = "deviceInstance.increase";
    public static final String DECREASE_DEVICE_INSTANCE_ROUTING_KEY = "deviceInstance.decrease";
    public static final String INCREASE_DEVICE_INSTANCE_QUEUE = "increase_device_instance_queue";
    public static final String DECREASE_DEVICE_INSTANCE_QUEUE = "decrease_device_instance_queue";

    public static final String DEVICE_BINDING_EXCHANGE = "flowfix.device-binding";
    public static final String DEVICE_BINDING_REQUEST_ROUTING_KEY = "flowfix.device-binding.requested.v1";
    public static final String DEVICE_BINDING_RESULT_ROUTING_KEY = "flowfix.device-binding.result.v1";
    public static final String DEVICE_BINDING_REQUEST_QUEUE = "flowfix.device.binding.requests";
    public static final String DEVICE_BINDING_RESULT_QUEUE = "flowfix.acl.device.binding.results";

}
