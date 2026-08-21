package com.schoolwork.epsys.device.client;


import com.schoolwork.epsys.model.device.Deviceinstance;
import com.schoolwork.epsys.model.device.MaintainRecord;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

@FeignClient(value="service-product")
public interface DeviceFeignClient {
    @RequestMapping("/deviceInstance/getDeviceInstanceListById")
    public List<Deviceinstance> getDeviceInstanceListById(@RequestBody List<Integer> id);
    @RequestMapping("/deviceInstance/updateDeviceInstanceStatus")
    public void updateDeviceInstanceStatus(@RequestParam(value = "deviceId") Integer id,
                                           @RequestParam(value = "status") String status);
}
