import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from legiongobar.app import main
    raise SystemExit(main())
