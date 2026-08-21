package com.schoolwork.epsys.approval.controller;


import com.schoolwork.epsys.model.approval.RepairmanApplication;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 用户申请审批接口预留控制器，用于后续承载申请审核相关能力。
 */
@RestController
@RequestMapping("/approval")
public class UserApplyController {


}
