package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.TableName;
import java.io.Serializable;
import java.util.Date;
import lombok.Data;

/**
 * @TableName devicecategory
 */
@TableName(value ="devicecategory")
@Data
public class Devicecategory implements Serializable {
    private Integer id;

    private String categoryName;

    private String description;

    private Date createAt;

    private static final long serialVersionUID = 1L;
}