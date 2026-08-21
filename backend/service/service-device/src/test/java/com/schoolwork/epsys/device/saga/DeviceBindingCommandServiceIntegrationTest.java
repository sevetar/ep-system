package com.schoolwork.epsys.device.saga;

import com.schoolwork.epsys.model.shared.DeviceBindingRequestedEventV1;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.time.Instant;

import static com.schoolwork.epsys.model.shared.DeviceBindingContracts.*;
import static org.junit.jupiter.api.Assertions.assertEquals;

@SpringBootTest(properties = {
        "spring.cloud.nacos.discovery.enabled=false",
        "spring.cloud.discovery.enabled=false"
})
@ActiveProfiles("test")
class DeviceBindingCommandServiceIntegrationTest {

    private static final int DEVICE_ID = 99881;
    private static final int USER_ID = 99882;

    @Autowired
    private DeviceBindingCommandService commandService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @BeforeEach
    void setUp() {
        cleanRows();
        jdbcTemplate.update("""
                INSERT INTO deviceinstance (id, model_id, serial_number, status, location)
                VALUES (?, 1, ?, '闲置', 'SAGA_TEST')
                """, DEVICE_ID, "SAGA-IT-" + DEVICE_ID);
    }

    @AfterEach
    void tearDown() {
        cleanRows();
    }

    @Test
    void bindAndUnbindAreIdempotentAndProduceTransactionalResults() {
        DeviceBindingRequestedEventV1 bind = event("bind-1", BIND_REQUESTED);
        commandService.handle(bind);
        commandService.handle(bind);

        assertEquals("使用", status());
        assertEquals(1, count("device_binding_command", "bind-1"));
        assertEquals(1, count("device_binding_result_outbox", "bind-1"));
        assertEquals("SUCCEEDED", result("bind-1"));

        DeviceBindingRequestedEventV1 unbind = event("unbind-1", UNBIND_REQUESTED);
        commandService.handle(unbind);

        assertEquals("闲置", status());
        assertEquals("SUCCEEDED", result("unbind-1"));
    }

    @Test
    void statusConflictReturnsFailedResultWithoutChangingDevice() {
        jdbcTemplate.update("UPDATE deviceinstance SET status = '维修中' WHERE id = ?", DEVICE_ID);

        commandService.handle(event("conflict-1", BIND_REQUESTED));

        assertEquals("维修中", status());
        assertEquals("FAILED", result("conflict-1"));
        assertEquals("DEVICE_STATUS_CONFLICT", jdbcTemplate.queryForObject(
                "SELECT reason_code FROM device_binding_command WHERE request_id = ?",
                String.class, "conflict-1"));
    }

    private DeviceBindingRequestedEventV1 event(String requestId, String eventType) {
        return new DeviceBindingRequestedEventV1(SCHEMA_VERSION, "event-" + requestId,
                requestId, eventType, USER_ID, DEVICE_ID, Instant.now());
    }

    private String status() {
        return jdbcTemplate.queryForObject("SELECT status FROM deviceinstance WHERE id = ?",
                String.class, DEVICE_ID);
    }

    private int count(String table, String requestId) {
        return jdbcTemplate.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE request_id = ?",
                Integer.class, requestId);
    }

    private String result(String requestId) {
        return jdbcTemplate.queryForObject(
                "SELECT result_status FROM device_binding_command WHERE request_id = ?",
                String.class, requestId);
    }

    private void cleanRows() {
        jdbcTemplate.update("DELETE FROM device_binding_result_outbox WHERE device_id = ?", DEVICE_ID);
        jdbcTemplate.update("DELETE FROM device_binding_command WHERE device_id = ?", DEVICE_ID);
        jdbcTemplate.update("DELETE FROM deviceinstance WHERE id = ?", DEVICE_ID);
    }
}
