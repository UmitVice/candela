package store

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/pressly/goose/v3"
	_ "modernc.org/sqlite"

	"github.com/UmitVice/candela/services/gateway/internal/store/db"
)

//go:embed migrations/*.sql
var migrations embed.FS

type Store struct {
	DB *sql.DB
	Q  *db.Queries
}

func Open(ctx context.Context, path string, log *slog.Logger) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("create db dir: %w", err)
	}
	dsn := "file:" + path + "?_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)&_pragma=synchronous(NORMAL)&_txlock=immediate"
	conn, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	conn.SetMaxOpenConns(4)
	conn.SetConnMaxIdleTime(5 * time.Minute)
	if err := conn.PingContext(ctx); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("open %s: %w", path, err)
	}
	provider, err := goose.NewProvider(goose.DialectSQLite3, conn, mustSub(migrations, "migrations"))
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	results, err := provider.Up(ctx)
	if err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	for _, r := range results {
		log.Info("migration applied", "version", r.Source.Version, "duration", r.Duration)
	}
	return &Store{DB: conn, Q: db.New(conn)}, nil
}

func (s *Store) Ping(ctx context.Context) error { return s.DB.PingContext(ctx) }

func (s *Store) Close() error { return s.DB.Close() }
