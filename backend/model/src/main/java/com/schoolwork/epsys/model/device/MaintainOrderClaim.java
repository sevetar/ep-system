package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/**
 * 维护工单领取记录，同时作为抢单幂等记录和工单唯一归属凭证。
 */
@Data
@TableName("maintain_order_claim")
public class MaintainOrderClaim implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Integer orderId;

    private Integer repairmanId;

    private String requestId;

    private Date claimedAt;

    private static final long serialVersionUID = 1L;
}
