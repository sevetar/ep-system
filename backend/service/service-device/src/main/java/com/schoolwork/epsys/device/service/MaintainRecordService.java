package com.schoolwork.epsys.device.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.schoolwork.epsys.model.device.MaintainRecord;
import org.springframework.transaction.annotation.Transactional;

/**
* @author 27959
* @description 针对表【maintain_record】的数据库操作Service
* @createDate 2025-04-07 08:24:12
*/


public interface MaintainRecordService extends IService<MaintainRecord> {

    /**
     * 在同一事务中写入唯一领取记录并更新工单，requestId 用于识别幂等重试。
     */
    @Transactional
    ClaimOrderResult claimOrder(Integer orderId, Integer repairmanId, String requestId);
}
