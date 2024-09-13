import argparse
import copy
import json
import os
from typing import Optional

import vana
from vana.chain_data import Proof, ProofData
from vana.contracts import contracts
from vana.utils.web3 import as_wad


class Client:
    @staticmethod
    def config() -> "config":
        parser = argparse.ArgumentParser()
        vana.ChainManager.add_args(parser)
        return vana.Config(parser, args=[])

    def __init__(self, config: vana.Config):
        if config is None:
            config = self.config()
        self.config = copy.deepcopy(config)

        self.wallet = vana.Wallet(config=self.config)
        self.chain_manager = vana.ChainManager(config=self.config)
        self.network = self.config.chain.network

        # Load contracts
        data_registry_contract_path = os.path.join(
            os.path.dirname(__file__),
            "contracts/DataRegistry.json"
        )
        with open(data_registry_contract_path) as f:
            self.data_registry_contract = self.chain_manager.web3.eth.contract(
                address=contracts[self.network]["DataRegistry"],
                abi=json.load(f)
            )
        tee_pool_contract_path = os.path.join(
            os.path.dirname(__file__),
            "contracts/TeePool.json"
        )
        with open(tee_pool_contract_path) as f:
            self.tee_pool_contract = self.chain_manager.web3.eth.contract(
                address=contracts[self.network]["TeePool"],
                abi=json.load(f)
            )

    # Data Registry

    def get_file(self, file_id: int):
        """
        Retrieve a file from the Data Registry contract
        :param file_id:
        :return: File<id, ownerAddress, url, addedAtBlock>
        """
        get_file_fn = self.data_registry_contract.functions.files(file_id)
        file = self.chain_manager.read_contract_fn(get_file_fn)
        (id, ownerAddress, url, addedAtBlock) = file
        if ownerAddress == "0x0000000000000000000000000000000000000000":
            return None
        return file

    def add_file(self, url: str, integrity_hash: Optional[str] = None):
        """
        Add a file to the Data Registry contract.
        :param url: URL where encrypted file is uploaded
        :param integrity_hash: Optional ETAG, last-modified, or other hash to verify file integrity
        :return: Transaction hex, Transaction receipt
        """
        add_file_fn = self.data_registry_contract.functions.addFile(url)
        return self.chain_manager.send_transaction(add_file_fn, self.wallet.hotkey)

    # TEE Pool Contract

    def register_tee(self, url: str):
        """
        Register a TEE compute node with the TEE Pool contract.
        :param url:
        :return: Transaction hex, Transaction receipt
        """
        register_fn = self.tee_pool_contract.functions.addTee(self.wallet.hotkey.address, url)
        return self.chain_manager.send_transaction(register_fn, self.wallet.hotkey)

    def add_proof(self, proof_data: ProofData, file_id: int | None = None, job_id: int | None = None):
        """
        Add a proof for a job to the Data Registry contract.

        :param file_id: Look up a file by File ID from the Data Registry contract
        :param job_id: Look up a file by the Job ID from the TEE Pool contract
        :param proof_data: A dictionary containing the proof data
        :return: Transaction hex, Transaction receipt
        """
        if (job_id is None) == (file_id is None):
            raise ValueError("One of job_id or file_id must be provided, but not both")

        signed_proof = Proof(data=proof_data).sign(self.wallet)
        proof_tuple = (
            signed_proof.signature,
            (
                as_wad(signed_proof.data.score),
                signed_proof.data.timestamp,
                signed_proof.data.metadata,
                signed_proof.data.proof_url,
                signed_proof.data.instruction,
            )
        )

        if file_id is not None:
            add_proof_fn = self.data_registry_contract.functions.addProof(file_id, proof_tuple)
        else:
            add_proof_fn = self.tee_pool_contract.functions.addProof(job_id, proof_tuple)
        return self.chain_manager.send_transaction(add_proof_fn, self.wallet.hotkey)

    def claim(self):
        """
        Claim any rewards for TEE validators for completed jobs
        :return: Transaction hex, Transaction receipt
        """
        claim_fn = self.tee_pool_contract.functions.claim()
        return self.chain_manager.send_transaction(claim_fn, self.wallet.hotkey)
