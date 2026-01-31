// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/TaskStatus.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__BUILDER_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "bird_deterrent_vineyard_msgs/msg/detail/task_status__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace builder
{

class Init_TaskStatus_extra
{
public:
  explicit Init_TaskStatus_extra(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus extra(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_extra_type arg)
  {
    msg_.extra = std::move(arg);
    return std::move(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_role
{
public:
  explicit Init_TaskStatus_role(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  Init_TaskStatus_extra role(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_role_type arg)
  {
    msg_.role = std::move(arg);
    return Init_TaskStatus_extra(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_y
{
public:
  explicit Init_TaskStatus_y(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  Init_TaskStatus_role y(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_y_type arg)
  {
    msg_.y = std::move(arg);
    return Init_TaskStatus_role(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_x
{
public:
  explicit Init_TaskStatus_x(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  Init_TaskStatus_y x(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_x_type arg)
  {
    msg_.x = std::move(arg);
    return Init_TaskStatus_y(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_type
{
public:
  explicit Init_TaskStatus_type(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  Init_TaskStatus_x type(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_type_type arg)
  {
    msg_.type = std::move(arg);
    return Init_TaskStatus_x(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_task_id
{
public:
  explicit Init_TaskStatus_task_id(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  Init_TaskStatus_type task_id(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_task_id_type arg)
  {
    msg_.task_id = std::move(arg);
    return Init_TaskStatus_type(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_robot_id
{
public:
  explicit Init_TaskStatus_robot_id(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  Init_TaskStatus_task_id robot_id(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_robot_id_type arg)
  {
    msg_.robot_id = std::move(arg);
    return Init_TaskStatus_task_id(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_event
{
public:
  explicit Init_TaskStatus_event(::bird_deterrent_vineyard_msgs::msg::TaskStatus & msg)
  : msg_(msg)
  {}
  Init_TaskStatus_robot_id event(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_event_type arg)
  {
    msg_.event = std::move(arg);
    return Init_TaskStatus_robot_id(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

class Init_TaskStatus_t
{
public:
  Init_TaskStatus_t()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_TaskStatus_event t(::bird_deterrent_vineyard_msgs::msg::TaskStatus::_t_type arg)
  {
    msg_.t = std::move(arg);
    return Init_TaskStatus_event(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::TaskStatus msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::bird_deterrent_vineyard_msgs::msg::TaskStatus>()
{
  return bird_deterrent_vineyard_msgs::msg::builder::Init_TaskStatus_t();
}

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK_STATUS__BUILDER_HPP_
