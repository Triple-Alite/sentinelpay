// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Address} from "@openzeppelin/contracts/utils/Address.sol";

contract SentinelEscrow is Ownable, EIP712, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;
    using Address for address payable;

    enum PaymentState {
        None,
        Created,
        Deposited,
        Approved,
        Held,
        Released,
        Refunded,
        Expired
    }

    enum RiskDecision {
        Allow,
        Review,
        Block
    }

    struct Payment {
        bytes32 referenceHash;
        address merchant;
        address customer;
        address token;
        uint256 amount;
        uint64 expiresAt;
        PaymentState state;
        RiskDecision decision;
    }

    bytes32 private constant RELEASE_TYPEHASH = keccak256(
        "ReleaseAuthorization(bytes32 paymentId,bytes32 referenceHash,address merchant,address customer,address token,uint256 amount,uint8 decision,uint64 expiration,uint256 chainId,address contractAddress,uint256 nonce)"
    );
    uint64 public constant REVIEW_GRACE_PERIOD = 7 days;

    address public authorizer;
    mapping(address token => bool allowed) public allowedTokens;
    mapping(bytes32 paymentId => Payment payment) public payments;
    mapping(bytes32 paymentId => mapping(uint256 nonce => bool used)) public usedAuthorizationNonces;
    mapping(address token => uint256 amount) public totalEscrowed;

    event PaymentCreated(bytes32 indexed paymentId, bytes32 indexed referenceHash, address indexed merchant, address token, uint256 amount, uint64 expiresAt);
    event PaymentDeposited(bytes32 indexed paymentId, address indexed customer, address token, uint256 amount);
    event PaymentAssessed(bytes32 indexed paymentId, RiskDecision decision);
    event PaymentApproved(bytes32 indexed paymentId);
    event PaymentHeld(bytes32 indexed paymentId, RiskDecision decision);
    event PaymentReleased(bytes32 indexed paymentId, address indexed merchant, uint256 amount);
    event PaymentRefunded(bytes32 indexed paymentId, address indexed customer, uint256 amount);
    event PaymentExpired(bytes32 indexed paymentId);
    event TokenAllowlistUpdated(address indexed token, bool allowed);
    event AuthorizerUpdated(address indexed authorizer);
    event EmergencyPaused(address indexed account);
    event EmergencyUnpaused(address indexed account);

    error InvalidPayment();
    error InvalidState();
    error InvalidAmount();
    error InvalidAddress();
    error UnsupportedToken();
    error PaymentExpiredError();
    error Unauthorized();
    error InvalidAuthorization();
    error AuthorizationAlreadyUsed();
    error RefundUnavailable();

    modifier onlyAuthorizer() {
        if (msg.sender != authorizer) revert Unauthorized();
        _;
    }

    constructor(address initialOwner, address initialAuthorizer)
        Ownable(initialOwner)
        EIP712("SentinelEscrow", "1")
    {
        if (initialAuthorizer == address(0)) revert InvalidAddress();
        authorizer = initialAuthorizer;
    }

    function setAuthorizer(address nextAuthorizer) external onlyOwner {
        if (nextAuthorizer == address(0)) revert InvalidAddress();
        authorizer = nextAuthorizer;
        emit AuthorizerUpdated(nextAuthorizer);
    }

    function setTokenAllowed(address token, bool allowed) external onlyOwner {
        if (token == address(0)) revert InvalidAddress();
        allowedTokens[token] = allowed;
        emit TokenAllowlistUpdated(token, allowed);
    }

    function createPayment(
        bytes32 paymentId,
        bytes32 referenceHash,
        address token,
        uint256 amount,
        uint64 expiresAt
    ) external whenNotPaused {
        if (paymentId == bytes32(0) || referenceHash == bytes32(0)) revert InvalidPayment();
        if (payments[paymentId].state != PaymentState.None) revert InvalidPayment();
        if (msg.sender == address(0)) revert InvalidAddress();
        if (amount == 0) revert InvalidAmount();
        if (expiresAt <= block.timestamp) revert PaymentExpiredError();
        if (token != address(0) && !allowedTokens[token]) revert UnsupportedToken();

        payments[paymentId] = Payment({
            referenceHash: referenceHash,
            merchant: msg.sender,
            customer: address(0),
            token: token,
            amount: amount,
            expiresAt: expiresAt,
            state: PaymentState.Created,
            decision: RiskDecision.Review
        });
        emit PaymentCreated(paymentId, referenceHash, msg.sender, token, amount, expiresAt);
    }

    function depositNative(bytes32 paymentId) external payable nonReentrant whenNotPaused {
        Payment storage payment = payments[paymentId];
        _validateDeposit(payment, address(0));
        if (msg.value != payment.amount) revert InvalidAmount();
        payment.customer = msg.sender;
        payment.state = PaymentState.Deposited;
        totalEscrowed[address(0)] += msg.value;
        emit PaymentDeposited(paymentId, msg.sender, address(0), msg.value);
    }

    function depositToken(bytes32 paymentId) external nonReentrant whenNotPaused {
        Payment storage payment = payments[paymentId];
        _validateDeposit(payment, payment.token);
        if (payment.token == address(0) || !allowedTokens[payment.token]) revert UnsupportedToken();
        payment.customer = msg.sender;
        payment.state = PaymentState.Deposited;
        totalEscrowed[payment.token] += payment.amount;
        IERC20(payment.token).safeTransferFrom(msg.sender, address(this), payment.amount);
        emit PaymentDeposited(paymentId, msg.sender, payment.token, payment.amount);
    }

    function assessPayment(bytes32 paymentId, RiskDecision decision) external onlyAuthorizer {
        Payment storage payment = payments[paymentId];
        if (payment.state != PaymentState.Deposited && payment.state != PaymentState.Held) revert InvalidState();
        payment.decision = decision;
        if (decision == RiskDecision.Allow) {
            payment.state = PaymentState.Approved;
            emit PaymentApproved(paymentId);
        } else {
            payment.state = PaymentState.Held;
            emit PaymentHeld(paymentId, decision);
        }
        emit PaymentAssessed(paymentId, decision);
    }

    function holdPayment(bytes32 paymentId) external onlyAuthorizer {
        Payment storage payment = payments[paymentId];
        if (payment.state != PaymentState.Deposited && payment.state != PaymentState.Approved) revert InvalidState();
        payment.state = PaymentState.Held;
        payment.decision = RiskDecision.Review;
        emit PaymentHeld(paymentId, RiskDecision.Review);
        emit PaymentAssessed(paymentId, RiskDecision.Review);
    }

    function resolveReview(bytes32 paymentId, bool approve) external onlyOwner {
        Payment storage payment = payments[paymentId];
        if (payment.state != PaymentState.Held) revert InvalidState();
        if (approve) {
            payment.state = PaymentState.Approved;
            payment.decision = RiskDecision.Allow;
            emit PaymentApproved(paymentId);
        } else {
            payment.decision = RiskDecision.Block;
            emit PaymentHeld(paymentId, RiskDecision.Block);
        }
        emit PaymentAssessed(paymentId, payment.decision);
    }

    function releasePayment(
        bytes32 paymentId,
        uint64 authorizationExpiry,
        uint256 nonce,
        bytes calldata signature
    ) external nonReentrant whenNotPaused {
        Payment storage payment = payments[paymentId];
        if (payment.state != PaymentState.Approved || payment.decision != RiskDecision.Allow) revert InvalidState();
        if (msg.sender != payment.merchant) revert Unauthorized();
        if (authorizationExpiry < block.timestamp || authorizationExpiry > payment.expiresAt + REVIEW_GRACE_PERIOD) {
            revert InvalidAuthorization();
        }
        if (usedAuthorizationNonces[paymentId][nonce]) revert AuthorizationAlreadyUsed();

        bytes32 structHash = keccak256(
            abi.encode(
                RELEASE_TYPEHASH,
                paymentId,
                payment.referenceHash,
                payment.merchant,
                payment.customer,
                payment.token,
                payment.amount,
                uint8(RiskDecision.Allow),
                authorizationExpiry,
                block.chainid,
                address(this),
                nonce
            )
        );
        address recovered = ECDSA.recover(_hashTypedDataV4(structHash), signature);
        if (recovered != authorizer) revert InvalidAuthorization();

        usedAuthorizationNonces[paymentId][nonce] = true;
        payment.state = PaymentState.Released;
        totalEscrowed[payment.token] -= payment.amount;
        _transfer(payment.token, payment.merchant, payment.amount);
        emit PaymentReleased(paymentId, payment.merchant, payment.amount);
    }

    function refundPayment(bytes32 paymentId) external nonReentrant {
        Payment storage payment = payments[paymentId];
        if (
            payment.state != PaymentState.Deposited &&
            payment.state != PaymentState.Approved &&
            payment.state != PaymentState.Held
        ) revert InvalidState();
        if (msg.sender != owner() && !(msg.sender == payment.customer && block.timestamp >= payment.expiresAt + REVIEW_GRACE_PERIOD)) {
            revert RefundUnavailable();
        }
        payment.state = PaymentState.Refunded;
        totalEscrowed[payment.token] -= payment.amount;
        _transfer(payment.token, payment.customer, payment.amount);
        emit PaymentRefunded(paymentId, payment.customer, payment.amount);
    }

    function expirePayment(bytes32 paymentId) external {
        Payment storage payment = payments[paymentId];
        if (payment.state != PaymentState.Created || block.timestamp < payment.expiresAt) revert InvalidState();
        payment.state = PaymentState.Expired;
        emit PaymentExpired(paymentId);
    }

    function pause() external onlyOwner {
        _pause();
        emit EmergencyPaused(msg.sender);
    }

    function unpause() external onlyOwner {
        _unpause();
        emit EmergencyUnpaused(msg.sender);
    }

    function _validateDeposit(Payment storage payment, address token) private view {
        if (payment.state != PaymentState.Created) revert InvalidState();
        if (payment.token != token) revert UnsupportedToken();
        if (block.timestamp >= payment.expiresAt) revert PaymentExpiredError();
    }

    function _transfer(address token, address recipient, uint256 amount) private {
        if (token == address(0)) {
            payable(recipient).sendValue(amount);
        } else {
            IERC20(token).safeTransfer(recipient, amount);
        }
    }
}