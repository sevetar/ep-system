package com.schoolwork.epsys.approval.receiver;


import com.schoolwork.epsys.acl.client.AclFeignClient;
import com.schoolwork.epsys.approval.service.RepairmanApplicationService;
import com.schoolwork.epsys.model.approval.RepairmanApplication;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;

import static com.schoolwork.epsys.mq.constant.MqConst.REPAIR_APPLY_QUEUE;


@Component
public class ApplyMessageListener {

    @Autowired
    private RepairmanApplicationService repairmanApplicationService;

    @Autowired
    private AclFeignClient aclFeignClient;


    @RabbitListener(queues = REPAIR_APPLY_QUEUE)
    public void handleApplyMessage(RepairmanApplication repairmanApplication) throws Exception {
        System.out.println("收到申请消息：" + repairmanApplication);
        repairmanApplication.setCreateTime(new Date());
        // DTO 转换为实体并写入数据库
        repairmanApplicationService.save(repairmanApplication);
        // 自动审核逻辑
        if (isAutoPass(repairmanApplication)) {

//
            Integer userId = repairmanApplication.getUserId();
            Integer roleId = 3;
            Boolean success = aclFeignClient.addUsertoRole3(userId, roleId);
            // 审核通过
            repairmanApplication.setStatus("approved");
            repairmanApplication.setApproveComment("系统自动审核通过");

        } else {
            // 审核拒绝（也可以保留为 PENDING）
            repairmanApplication.setStatus("rejected");
            repairmanApplication.setApproveComment("系统自动审核未通过，信息不完整");
        }
        repairmanApplication.setApproveTime(new Date());

        // 更新审核状态
        repairmanApplicationService.updateById(repairmanApplication);
    }


    private boolean isAutoPass(RepairmanApplication app) {
        return app.getApplyReason() != null && !app.getApplyReason().trim().isEmpty();
//                && app.getQualificationProof() != null && !app.getQualificationProof().trim().isEmpty();
    }


}
