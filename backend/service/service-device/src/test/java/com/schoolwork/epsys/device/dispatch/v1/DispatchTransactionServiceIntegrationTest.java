package com.schoolwork.epsys.device.dispatch.v1;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "spring.cloud.nacos.discovery.enabled=false",
        "spring.cloud.discovery.enabled=false"
})
@ActiveProfiles("test")
class DispatchTransactionServiceIntegrationTest {

    private static final int ORDER_ID = 99001;
    private static final int DEVICE_ID = 99001;
    private static final int FIRST_WORKER_ID = 99101;
    private static final int WORKER_COUNT = 20;

    @Autowired
    private DispatchTransactionService transactionService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @BeforeEach
    void setUp() {
        cleanRows();
        jdbcTemplate.update("""
                INSERT INTO deviceinstance (id, model_id, serial_number, status, location)
                VALUES (?, 1, ?, '待维修', 'CAMPUS_EAST')
                """, DEVICE_ID, "DISPATCH-IT-" + DEVICE_ID);
        jdbcTemplate.update("""
                INSERT INTO maintain_record
                  (id, device_id, tenant_id, maintenance_type, priority, status, version)
                VALUES (?, ?, 'default', 'ELECTRICAL', 'NORMAL', '待领取', 0)
                """, ORDER_ID, DEVICE_ID);
        for (int i = 0; i < WORKER_COUNT; i++) {
            int workerId = FIRST_WORKER_ID + i;
            jdbcTemplate.update("""
                    INSERT INTO repairman_dispatch_profile
                      (worker_id, tenant_id, region_code, shift_status, available, capacity, active)
                    VALUES (?, 'default', 'CAMPUS_EAST', 'ON_DUTY', 1, 3, 1)
                    """, workerId);
            jdbcTemplate.update("INSERT INTO repairman_dispatch_skill (worker_id, skill_code) VALUES (?, 'ELECTRICAL')",
                    workerId);
        }
    }

    @AfterEach
    void tearDown() {
        cleanRows();
    }

    @Test
    void acceptedCommandIsIdempotentAndProducesOneSideEffect() {
        AssignmentCommandV1 command = command("idem-success", "dispatch-success", FIRST_WORKER_ID, 0);

        AssignmentReceiptV1 first = transactionService.assign(command, DispatchCommandHasher.hash(command));
        AssignmentReceiptV1 replay = transactionService.assign(command, DispatchCommandHasher.hash(command));

        assertEquals(ReceiptStatus.ACCEPTED, first.receiptStatus());
        assertEquals(1, first.observedVersion());
        assertEquals(ReceiptStatus.ALREADY_APPLIED, replay.receiptStatus());
        assertEquals(1, count("SELECT COUNT(*) FROM maintain_order_claim WHERE order_id = ?", ORDER_ID));
        assertEquals(1, count("SELECT COUNT(*) FROM dispatch_assignment WHERE idempotency_key = ?", "idem-success"));
        assertEquals(FIRST_WORKER_ID,
                jdbcTemplate.queryForObject("SELECT miantain_id FROM maintain_record WHERE id = ?", Integer.class, ORDER_ID));
        assertEquals(1,
                jdbcTemplate.queryForObject("SELECT version FROM maintain_record WHERE id = ?", Integer.class, ORDER_ID));
    }

    @Test
    void staleExpectedVersionHasNoBusinessSideEffect() {
        AssignmentCommandV1 command = command("idem-stale", "dispatch-stale", FIRST_WORKER_ID, 9);

        AssignmentReceiptV1 receipt = transactionService.assign(command, DispatchCommandHasher.hash(command));

        assertEquals(ReceiptStatus.VERSION_CONFLICT, receipt.receiptStatus());
        assertEquals(ReasonCode.VERSION_CONFLICT, receipt.reasonCode());
        assertEquals(0, count("SELECT COUNT(*) FROM maintain_order_claim WHERE order_id = ?", ORDER_ID));
        assertNull(jdbcTemplate.queryForObject(
                "SELECT miantain_id FROM maintain_record WHERE id = ?", Integer.class, ORDER_ID));
        assertEquals(0,
                jdbcTemplate.queryForObject("SELECT version FROM maintain_record WHERE id = ?", Integer.class, ORDER_ID));
    }

    @ParameterizedTest
    @ValueSource(ints = {20, 50, 100})
    void concurrentCommandsHaveExactlyOneWinner(int concurrency) throws Exception {
        var executor = Executors.newFixedThreadPool(Math.min(concurrency, 32));
        try {
            List<Callable<AssignmentReceiptV1>> tasks = new ArrayList<>();
            for (int i = 0; i < concurrency; i++) {
                int workerId = FIRST_WORKER_ID;
                String suffix = Integer.toString(i);
                tasks.add(() -> {
                    AssignmentCommandV1 command = command(
                            "idem-concurrent-" + suffix, "dispatch-concurrent-" + suffix, workerId, 0);
                    return transactionService.assign(command, DispatchCommandHasher.hash(command));
                });
            }
            var futures = executor.invokeAll(tasks, 30, TimeUnit.SECONDS);
            long accepted = 0;
            for (var future : futures) {
                assertFalse(future.isCancelled());
                AssignmentReceiptV1 receipt = future.get();
                if (receipt.receiptStatus() == ReceiptStatus.ACCEPTED) {
                    accepted++;
                }
            }
            assertEquals(1, accepted);
            assertEquals(1, count("SELECT COUNT(*) FROM maintain_order_claim WHERE order_id = ?", ORDER_ID));
            assertEquals(1,
                    jdbcTemplate.queryForObject("SELECT version FROM maintain_record WHERE id = ?", Integer.class, ORDER_ID));
            assertNotNull(jdbcTemplate.queryForObject(
                    "SELECT miantain_id FROM maintain_record WHERE id = ?", Integer.class, ORDER_ID));
        } finally {
            executor.shutdownNow();
        }
    }

    private AssignmentCommandV1 command(String key, String dispatchId, int workerId, int expectedVersion) {
        return new AssignmentCommandV1(CONTRACT_VERSION, "trace-it", "event-it-" + dispatchId,
                dispatchId, key, DEFAULT_TENANT, Integer.toString(ORDER_ID),
                Integer.toString(workerId), expectedVersion);
    }

    private int count(String sql, Object argument) {
        return jdbcTemplate.queryForObject(sql, Integer.class, argument);
    }

    private void cleanRows() {
        jdbcTemplate.update("DELETE FROM dispatch_assignment WHERE order_id = ?", ORDER_ID);
        jdbcTemplate.update("DELETE FROM maintain_order_claim WHERE order_id = ?", ORDER_ID);
        jdbcTemplate.update("DELETE FROM maintain_record WHERE id = ?", ORDER_ID);
        jdbcTemplate.update("DELETE FROM repairman_dispatch_skill WHERE worker_id BETWEEN ? AND ?",
                FIRST_WORKER_ID, FIRST_WORKER_ID + WORKER_COUNT - 1);
        jdbcTemplate.update("DELETE FROM repairman_dispatch_profile WHERE worker_id BETWEEN ? AND ?",
                FIRST_WORKER_ID, FIRST_WORKER_ID + WORKER_COUNT - 1);
        jdbcTemplate.update("DELETE FROM deviceinstance WHERE id = ?", DEVICE_ID);
    }
}
