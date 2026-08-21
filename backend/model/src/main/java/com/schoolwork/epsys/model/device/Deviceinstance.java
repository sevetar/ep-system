package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.TableName;
import java.io.Serializable;
import java.util.Date;
import lombok.Data;

/**
 * @TableName deviceinstance
 */
@TableName(value ="deviceinstance")
@Data
public class Deviceinstance implements Serializable {
    private Integer id;

    private Integer modelId;

    private String serialNumber;

    private Object status;

    private Date createAt;

    private String location;

    private static final long serialVersionUID = 1L;
}