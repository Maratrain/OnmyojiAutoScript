# This Python file uses the following encoding: utf-8
# copy from alas https://github.com/LmeSzinc/AzurLaneAutoScript
from deploy.config import DeployConfig
from deploy.logger import logger
from deploy.utils import *


class GitManager(DeployConfig):
    @cached_property
    def git(self):
        return self.filepath('GitExecutable')

    @staticmethod
    def remove(file):
        try:
            os.remove(file)
            logger.info(f'[更新器] 已删除文件: {file}')
        except FileNotFoundError:
            logger.info(f'[更新器] 未找到文件: {file}')

    def git_repository_init(
            self, repo, source='origin', branch='master',
            proxy='', ssl_verify=True, keep_changes=False
    ):
        logger.hr('Git 初始化', 1)
        if not self.execute(f'"{self.git}" init', allow_failure=True):
            self.remove('./.git/config')
            self.remove('./.git/index')
            self.remove('./.git/HEAD')
            self.execute(f'"{self.git}" init')

        logger.hr('设置 Git 代理', 1)
        if proxy:
            self.execute(f'"{self.git}" config --local http.proxy {proxy}')
            self.execute(f'"{self.git}" config --local https.proxy {proxy}')
        else:
            self.execute(f'"{self.git}" config --local --unset http.proxy', allow_failure=True)
            self.execute(f'"{self.git}" config --local --unset https.proxy', allow_failure=True)

        if ssl_verify:
            self.execute(f'"{self.git}" config --local http.sslVerify true', allow_failure=True)
        else:
            self.execute(f'"{self.git}" config --local http.sslVerify false', allow_failure=True)

        logger.hr('设置 Git 仓库', 1)
        if not self.execute(f'"{self.git}" remote set-url {source} {repo}', allow_failure=True):
            self.execute(f'"{self.git}" remote add {source} {repo}')

        logger.hr('获取仓库分支', 1)
        self.execute(f'"{self.git}" fetch {source} {branch}')

        logger.hr('拉取仓库分支', 1)
        # Remove git lock
        for lock_file in [
            './.git/index.lock',
            './.git/HEAD.lock',
            './.git/refs/heads/master.lock',
        ]:
            if os.path.exists(lock_file):
                logger.info(f'[更新器] 锁文件 {lock_file} 已存在，正在删除')
                os.remove(lock_file)
        if keep_changes:
            if self.execute(f'"{self.git}" stash', allow_failure=True):
                self.execute(f'"{self.git}" pull --ff-only {source} {branch}')
                if self.execute(f'"{self.git}" stash pop', allow_failure=True):
                    pass
                else:
                    # No local changes to existing files, untracked files not included
                    logger.info('[更新器] stash pop 失败，似乎没有本地更改，改为跳过')
            else:
                logger.info('[更新器] stash 失败，这可能是首次安装，改为丢弃更改')
                self.execute(f'"{self.git}" reset --hard {source}/{branch}')
                self.execute(f'"{self.git}" pull --ff-only {source} {branch}')
        else:
            self.execute(f'"{self.git}" reset --hard {source}/{branch}')
            self.execute(f'"{self.git}" pull --ff-only {source} {branch}')

        logger.hr('显示版本', 1)
        self.execute(f'"{self.git}" --no-pager log --no-merges -1')

    def git_install(self):
        logger.hr('更新 OAS', 0)

        if not self.AutoUpdate:
            logger.info('[更新器] AutoUpdate 未启用，跳过')
            return

        self.git_repository_init(
            repo=self.Repository,
            source='origin',
            branch=self.Branch,
            proxy=self.GitProxy,
            ssl_verify=self.SSLVerify,
            keep_changes=self.KeepLocalChanges,
        )
