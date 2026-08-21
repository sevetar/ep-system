package com.schoolwork.epsys.device.dispatch.trigger;

import com.schoolwork.epsys.device.mapper.MaintainRecordMapper;
import com.schoolwork.epsys.model.device.MaintainRecord;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Date;

@Component
public class ExpiredClaimWindowScanner {

    private final MaintainRecordMapper maintainRecordMapper;
    private final DispatchTriggerService triggerService;
    private final boolean enabled;
    private final int batchSize;

    public ExpiredClaimWindowScanner(MaintainRecordMapper maintainRecordMapper,
                                     DispatchTriggerService triggerService,
                                     @Value("${dispatch.auto.enabled:false}") boolean enabled,
                                     @Value("${dispatch.auto.scan-batch-size:100}") int batchSize) {
        this.maintainRecordMapper = maintainRecordMapper;
        this.triggerService = triggerService;
        this.enabled = enabled;
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${dispatch.auto.scan-delay-ms:30000}")
    public void scan() {
        if (!enabled) {
            return;
        }
        for (MaintainRecord order : maintainRecordMapper.findExpiredClaimWindows(new Date(), batchSize)) {
            int version = order.getVersion() == null ? 0 : order.getVersion();
            triggerService.trigger(order.getId(), DispatchTriggerType.CLAIM_TIMEOUT,
                    "deadline:" + order.getClaimDeadline().getTime() + ":v" + version);
        }
    }
}
