package com.schoolwork.epsys.device.service.impl;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.schoolwork.epsys.device.mapper.MaintainOrderClaimMapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.schoolwork.epsys.model.device.MaintainRecord;
import com.schoolwork.epsys.device.mapper.MaintainRecordMapper;
import com.schoolwork.epsys.device.order.MaintainOrderEvent;
import com.schoolwork.epsys.device.order.OrderLifecycleService;
import com.schoolwork.epsys.device.order.OrderStateMachine;
import com.schoolwork.epsys.device.order.OrderTransitionContext;
import com.schoolwork.epsys.model.device.MaintainOrderClaim;
import com.schoolwork.epsys.device.service.ClaimOrderConflictException;
import com.schoolwork.epsys.device.service.ClaimOrderResult;
import com.schoolwork.epsys.device.service.MaintainRecordService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;

/**
* @author 27959
* @description 针对表【maintain_record】的数据库操作Service实现
* @createDate 2025-04-07 08:24:12
*/
@Service
public class MaintainRecordServiceImpl extends ServiceImpl<MaintainRecordMapper, MaintainRecord>
        implements MaintainRecordService {

    private static final String STATUS_APPROVED = "已通过";
    private static final String STATUS_WAITING_FOR_CLAIM = "待领取";
    private static final String STATUS_IN_PROGRESS = "维护中";

    @Autowired
    private MaintainOrderClaimMapper maintainOrderClaimMapper;

    @Autowired
    private OrderLifecycleService lifecycleService;

    @Autowired
    private OrderStateMachine stateMachine;

    @Override
    @Transactional
    public ClaimOrderResult claimOrder(Integer orderId, Integer repairmanId, String requestId) {
        MaintainOrderClaim requestRecord = maintainOrderClaimMapper.selectOne(
                Wrappers.<MaintainOrderClaim>lambdaQuery()
                        .eq(MaintainOrderClaim::getRequestId, requestId));
        if (requestRecord != null) {
            boolean sameRequest = orderId.equals(requestRecord.getOrderId())
                    && repairmanId.equals(requestRecord.getRepairmanId());
            return sameRequest
                    ? ClaimOrderResult.IDEMPOTENT_SUCCESS
                    : ClaimOrderResult.IDEMPOTENCY_KEY_CONFLICT;
        }

        MaintainOrderClaim orderClaim = maintainOrderClaimMapper.selectOne(
                Wrappers.<MaintainOrderClaim>lambdaQuery()
                        .eq(MaintainOrderClaim::getOrderId, orderId));
        if (orderClaim != null) {
            return ClaimOrderResult.ORDER_ALREADY_CLAIMED;
        }

        // Redisson 锁内重新读取，保证后进入临界区的请求看到最新业务状态和 version。
        MaintainRecord record = this.getById(orderId);
        if (record == null) {
            return ClaimOrderResult.ORDER_NOT_FOUND;
        }
        if (!stateMachine.canTransition(record.getStatus(), MaintainOrderEvent.MANUAL_CLAIM)) {
            return ClaimOrderResult.ORDER_NOT_CLAIMABLE;
        }
        if (record.getMiantainId() != null) {
            return ClaimOrderResult.ORDER_ALREADY_CLAIMED;
        }

        MaintainOrderClaim claim = new MaintainOrderClaim();
        claim.setOrderId(orderId);
        claim.setRepairmanId(repairmanId);
        claim.setRequestId(requestId);
        claim.setClaimedAt(new Date());
        maintainOrderClaimMapper.insert(claim);

        lifecycleService.apply(record, MaintainOrderEvent.MANUAL_CLAIM,
                OrderTransitionContext.assignment(repairmanId, new Date()));
        if (!this.updateById(record)) {
            throw new ClaimOrderConflictException("工单版本已发生变化");
        }
        return ClaimOrderResult.SUCCESS;
    }

}


