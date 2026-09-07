-- Execute inside an explicit transaction owned by the migration executor.
-- The procedural block is atomic; it does not manage transaction boundaries.
DO $reconcile$
DECLARE
    pipeline_table regclass := to_regclass('governance.pipeline_runs');
    quality_table regclass := to_regclass('governance.data_quality_results');
    status_attribute smallint;
    run_required boolean;
    type_required boolean;
    null_count bigint;
    existing_check record;
    normalized text;
    state_count integer;
    equivalent_found boolean := false;
BEGIN
    IF pipeline_table IS NULL OR quality_table IS NULL THEN
        RAISE EXCEPTION '003 requires governance.pipeline_runs and governance.data_quality_results; apply 001 first';
    END IF;

    -- Serialize reconciliation and exclude writes between preflight and DDL.
    LOCK TABLE governance.pipeline_runs, governance.data_quality_results
        IN SHARE ROW EXCLUSIVE MODE;

    SELECT attnum INTO status_attribute
    FROM pg_attribute
    WHERE attrelid = pipeline_table AND attname = 'status'
        AND attnum > 0 AND NOT attisdropped;
    SELECT attnotnull INTO run_required
    FROM pg_attribute
    WHERE attrelid = quality_table AND attname = 'run_id'
        AND attnum > 0 AND NOT attisdropped;
    SELECT attnotnull INTO type_required
    FROM pg_attribute
    WHERE attrelid = quality_table AND attname = 'check_type'
        AND attnum > 0 AND NOT attisdropped;
    IF status_attribute IS NULL OR run_required IS NULL OR type_required IS NULL THEN
        RAISE EXCEPTION '003 requires pipeline_runs.status and data_quality_results.run_id/check_type';
    END IF;

    -- Prove a narrow expression grammar, not merely matching names or literals.
    -- IN deparses as = ANY. Also accept a disjunction of three equalities.
    -- Unknown expressions fail closed, even when they might be equivalent.
    FOR existing_check IN
        SELECT conname, convalidated, connoinherit, conkey,
            pg_get_expr(conbin, conrelid) AS expression
        FROM pg_constraint
        WHERE conrelid = pipeline_table AND contype = 'c'
            AND (status_attribute = ANY (conkey)
                OR conname = 'pipeline_runs_status_check')
    LOOP
        normalized := existing_check.expression;
        normalized := replace(normalized, '''RUNNING''', 'RUNNING');
        normalized := replace(normalized, '''SUCCESS''', 'SUCCESS');
        normalized := replace(normalized, '''FAILED''', 'FAILED');
        normalized := replace(normalized, '"status"', 'status');
        normalized := regexp_replace(normalized,
            '::(text|character varying)(\[\])?', '', 'g');
        normalized := regexp_replace(normalized, '[[:space:]()]', '', 'g');

        SELECT count(DISTINCT token[1]) INTO state_count
        FROM regexp_matches(normalized, '(RUNNING|SUCCESS|FAILED)', 'g') AS token;

        IF existing_check.connoinherit
            OR existing_check.conkey IS DISTINCT FROM ARRAY[status_attribute]
            OR state_count <> 3
            OR NOT (
                normalized ~ '^status=ANYARRAY\[(RUNNING|SUCCESS|FAILED),(RUNNING|SUCCESS|FAILED),(RUNNING|SUCCESS|FAILED)\]$'
                OR normalized ~ '^status=(RUNNING|SUCCESS|FAILED)ORstatus=(RUNNING|SUCCESS|FAILED)ORstatus=(RUNNING|SUCCESS|FAILED)$'
            ) THEN
            RAISE EXCEPTION '003 conflicting or unsupported status CHECK: %', existing_check.conname;
        END IF;
        equivalent_found := true;
    END LOOP;

    IF NOT equivalent_found AND EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = pipeline_table AND conname = 'pipeline_runs_status_check'
    ) THEN
        RAISE EXCEPTION '003 constraint name pipeline_runs_status_check is already occupied';
    END IF;

    IF NOT run_required THEN
        SELECT COUNT(*) INTO null_count
        FROM governance.data_quality_results WHERE run_id IS NULL;
        IF null_count <> 0 THEN
            RAISE EXCEPTION '003 cannot require data_quality_results.run_id: % NULL rows', null_count;
        END IF;
    END IF;
    IF NOT type_required THEN
        SELECT COUNT(*) INTO null_count
        FROM governance.data_quality_results WHERE check_type IS NULL;
        IF null_count <> 0 THEN
            RAISE EXCEPTION '003 cannot require data_quality_results.check_type: % NULL rows', null_count;
        END IF;
    END IF;

    IF NOT equivalent_found THEN
        ALTER TABLE governance.pipeline_runs
            ADD CONSTRAINT pipeline_runs_status_check
            CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'));
    ELSE
        -- An equivalent but unvalidated constraint must cover existing rows too.
        FOR existing_check IN
            SELECT conname FROM pg_constraint
            WHERE conrelid = pipeline_table AND contype = 'c'
                AND status_attribute = ANY (conkey) AND NOT convalidated
        LOOP
            EXECUTE format('ALTER TABLE governance.pipeline_runs VALIDATE CONSTRAINT %I',
                existing_check.conname);
        END LOOP;
    END IF;
    IF NOT run_required THEN
        ALTER TABLE governance.data_quality_results
            ALTER COLUMN run_id SET NOT NULL;
    END IF;
    IF NOT type_required THEN
        ALTER TABLE governance.data_quality_results
            ALTER COLUMN check_type SET NOT NULL;
    END IF;
END
$reconcile$;
