// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Task.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__BUILDER_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "bird_deterrent_vineyard_msgs/msg/detail/task__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

namespace builder
{

class Init_Task_score
{
public:
  explicit Init_Task_score(::bird_deterrent_vineyard_msgs::msg::Task & msg)
  : msg_(msg)
  {}
  ::bird_deterrent_vineyard_msgs::msg::Task score(::bird_deterrent_vineyard_msgs::msg::Task::_score_type arg)
  {
    msg_.score = std::move(arg);
    return std::move(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

class Init_Task_assigned_secondary
{
public:
  explicit Init_Task_assigned_secondary(::bird_deterrent_vineyard_msgs::msg::Task & msg)
  : msg_(msg)
  {}
  Init_Task_score assigned_secondary(::bird_deterrent_vineyard_msgs::msg::Task::_assigned_secondary_type arg)
  {
    msg_.assigned_secondary = std::move(arg);
    return Init_Task_score(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

class Init_Task_assigned_primary
{
public:
  explicit Init_Task_assigned_primary(::bird_deterrent_vineyard_msgs::msg::Task & msg)
  : msg_(msg)
  {}
  Init_Task_assigned_secondary assigned_primary(::bird_deterrent_vineyard_msgs::msg::Task::_assigned_primary_type arg)
  {
    msg_.assigned_primary = std::move(arg);
    return Init_Task_assigned_secondary(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

class Init_Task_time
{
public:
  explicit Init_Task_time(::bird_deterrent_vineyard_msgs::msg::Task & msg)
  : msg_(msg)
  {}
  Init_Task_assigned_primary time(::bird_deterrent_vineyard_msgs::msg::Task::_time_type arg)
  {
    msg_.time = std::move(arg);
    return Init_Task_assigned_primary(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

class Init_Task_y
{
public:
  explicit Init_Task_y(::bird_deterrent_vineyard_msgs::msg::Task & msg)
  : msg_(msg)
  {}
  Init_Task_time y(::bird_deterrent_vineyard_msgs::msg::Task::_y_type arg)
  {
    msg_.y = std::move(arg);
    return Init_Task_time(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

class Init_Task_x
{
public:
  explicit Init_Task_x(::bird_deterrent_vineyard_msgs::msg::Task & msg)
  : msg_(msg)
  {}
  Init_Task_y x(::bird_deterrent_vineyard_msgs::msg::Task::_x_type arg)
  {
    msg_.x = std::move(arg);
    return Init_Task_y(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

class Init_Task_type
{
public:
  explicit Init_Task_type(::bird_deterrent_vineyard_msgs::msg::Task & msg)
  : msg_(msg)
  {}
  Init_Task_x type(::bird_deterrent_vineyard_msgs::msg::Task::_type_type arg)
  {
    msg_.type = std::move(arg);
    return Init_Task_x(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

class Init_Task_id
{
public:
  Init_Task_id()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_Task_type id(::bird_deterrent_vineyard_msgs::msg::Task::_id_type arg)
  {
    msg_.id = std::move(arg);
    return Init_Task_type(msg_);
  }

private:
  ::bird_deterrent_vineyard_msgs::msg::Task msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::bird_deterrent_vineyard_msgs::msg::Task>()
{
  return bird_deterrent_vineyard_msgs::msg::builder::Init_Task_id();
}

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__BUILDER_HPP_
